#!/usr/bin/env python3
"""Самотест сторінок landing-kit у headless Chrome (без сервера).
Збирає тестові копії брифу (фіктивний endpoint, thanks через #hash), «клікає» сторінку
і перевіряє: квіз проходить усі кроки, невалідний телефон блокується, валідний
нормалізується до +380..., UTM потрапляють у запит, event_id є, honeypot відсікає ботів.
Запуск: python selftest.py brief.json [шлях_до_chrome]
"""
import json, os, re, subprocess, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_landing as B

for _s in (sys.stdout, sys.stderr):  # кирилиця у виводі на Windows
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass

def find_chrome():
    """Порядок: аргумент 2, змінна CHROME_PATH, PATH, типові місця (Windows, macOS, Linux)."""
    if len(sys.argv) > 2: return sys.argv[2]
    if os.environ.get("CHROME_PATH"): return os.environ["CHROME_PATH"]
    for n in ("chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        w = shutil.which(n)
        if w: return w
    local = os.environ.get("LOCALAPPDATA", "")
    for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]:
        if os.path.exists(p): return p
    return None

CHROME = find_chrome()
if not CHROME:
    sys.exit("Chrome не знайдено. Вкажіть шлях: python selftest.py brief.json <шлях_до_chrome> або змінна CHROME_PATH.")

STUB = "<script>window.__sent=null;window.fetch=function(u,o){window.__sent=Object.fromEntries(new URLSearchParams(o.body.toString()));return Promise.resolve()};</script>"

TEST_QUIZ = """
<script>
setTimeout(function(){
 var out=[];function ok(n,c){out.push((c?'OK  ':'FAIL ')+n)}
 try{
  var n=document.querySelectorAll('#qbox .opt').length;ok('перше питання має варіанти',n>0);
  var guard=0;(function nxt(){var o=document.querySelector('#qbox .opt');if(o&&guard++<20){o.click();o.click();setTimeout(nxt,300)}else after()})();
  function after(){
  ok('після питань з’явилась форма контактів',!!document.getElementById('qf'));
  ok('подвійний клік не пропускає питання',guard===__QN__);
  var f=document.getElementById('qf');
  f.querySelector('[name=name]').value='Тест';f.querySelector('[name=phone]').value='12345';
  f.dispatchEvent(new Event('submit',{cancelable:true}));
  ok('невалідний телефон блокується',window.__sent===null&&/0XX/.test(f.querySelector('.err').textContent));
  f.querySelector('[name=phone]').value='067 123 45 67';
  f.dispatchEvent(new Event('submit',{cancelable:true}));
  setTimeout(function(){
   var s=window.__sent||{};
   ok('телефон нормалізовано',s.phone==='+380671234567');
   ok('є event_id',!!s.event_id);
   ok('UTM передано',s.utm_source==='facebook'&&s.utm_campaign==='test');
   ok('відповіді квізу в заявці',!!s.quiz&&s.quiz.split('|').length>=2);
   ok('перехід на сторінку подяки з eid',/#done\\?eid=/.test(location.href)||/#done/.test(location.hash+location.href));
   document.title=out.join('\\n');document.body.setAttribute('data-done','1');
  },500);
  }
 }catch(e){document.title='EXC '+e;document.body.setAttribute('data-done','1')}
},400);
</script>"""

TEST_LANDING = """
<script>
setTimeout(function(){
 var out=[];function ok(n,c){out.push((c?'OK  ':'FAIL ')+n)}
 try{
  var f=document.getElementById('lead');ok('форма є',!!f);
  f.querySelector('[name=phone]').value='abc';f.dispatchEvent(new Event('submit',{cancelable:true}));
  ok('невалідний телефон блокується',window.__sent===null);
  f.querySelector('[name=website]').value='http://spam';f.querySelector('[name=phone]').value='0671234567';
  f.dispatchEvent(new Event('submit',{cancelable:true}));
  ok('honeypot відсікає бота',window.__sent===null);
  f.querySelector('[name=website]').value='';f.dispatchEvent(new Event('submit',{cancelable:true}));
  setTimeout(function(){
   var s=window.__sent||{};
   ok('телефон нормалізовано',s.phone==='+380671234567');
   ok('є event_id',!!s.event_id);
   ok('UTM передано',s.utm_source==='facebook'&&s.utm_campaign==='test');
   ok('немає горизонтального скролу',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1);
   document.title=out.join('\\n');document.body.setAttribute('data-done','1')
  },500);
 }catch(e){document.title='EXC '+e;document.body.setAttribute('data-done','1')}
},400);
</script>"""

def main():
    b = json.load(open(sys.argv[1], encoding="utf-8-sig"))
    # у тесті піксель вимкнено: перевіряємо логіку сторінки, а Chrome не ходить у мережу за скриптом пікселя
    b.setdefault("tracking", {}).update({"endpoint": "https://example.invalid/exec", "thanks_url": "#done", "pixel_id": ""})
    tmp = tempfile.mkdtemp(prefix="lk_")
    B.sys.argv = [sys.argv[0], sys.argv[1]]
    B.build(b, tmp)
    p = os.path.join(tmp, "index.html")
    t = open(p, encoding="utf8").read()
    test = (TEST_QUIZ.replace("__QN__", str(len(b["quiz"]["questions"]))) if b.get("format") == "quiz" else TEST_LANDING)
    t = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + STUB, t, count=1).replace("</body>", test + "</body>")
    open(p, "w", encoding="utf8").write(t)
    url = "file:///" + p.replace("\\", "/") + "?utm_source=facebook&utm_campaign=test"
    prof = tempfile.mkdtemp(prefix="lkp_")
    r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}",
                        "--virtual-time-budget=6000", "--dump-dom", url], capture_output=True, text=True, encoding="utf8")
    m = re.search(r"<title>(.*?)</title>", r.stdout, re.S)
    res = m.group(1) if m else "немає результату"
    print(res.replace("&amp;", "&"))
    for _d in (tmp, prof):
        try: shutil.rmtree(_d)
        except OSError as e: print(f"Увага: не вдалося видалити тимчасову папку {_d}: {e}")
    sys.exit(1 if "FAIL" in res or "EXC" in res or res == "немає результату" else 0)

main()
