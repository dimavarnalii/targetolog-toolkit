#!/usr/bin/env python3
"""landing-kit: brief.json -> готова посадкова сторінка або квіз-воронка (без залежностей).

Запуск:  python build_landing.py brief.json            (результат у папці out/)
         python build_landing.py brief.json --out my    (інша папка)
Результат у папці out/: index.html, thanks.html і img/ (якщо є зображення). Усю папку out/ можна публікувати.
Файл lead_endpoint.gs у out/ не копіюється: його вставляють в Google Apps Script (див. README).
Весь CSS і JS вбудовані; шрифти системні, сторінка не залежить від зовнішніх бібліотек.
"""
import argparse, colorsys, html, json, os, re, shutil, sys

E = lambda s: html.escape(str(s), quote=True)

def emph(s):
    """**слово** у тексті стає акцентом (підсвітка), решта екранується."""
    return re.sub(r"\*\*(.+?)\*\*", r"<em>\1</em>", E(s))

# ---------------------------------------------------------------- кольори
def _rgb(h):
    h = h.lstrip("#")
    if len(h) == 3: h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def shift(hexc, dh=0.07, dl=0.0):
    r, g, b = [x / 255 for x in _rgb(hexc)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((h + dh) % 1, max(0, min(1, l + dl)), s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

def on_color(hexc):
    r, g, b = _rgb(hexc)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#111111" if lum > 0.62 else "#ffffff"

# ---------------------------------------------------------------- теми
THEMES = {
    "fresh": dict(bg="#ffffff", bg2="#f4f6fb", tx="#10131a", mut="#586173", card="#ffffff", line="#e3e7f0",
                  r="18px", sh="0 10px 30px -12px rgba(20,30,70,.22)", bw="1px", hf="system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif",
                  hw="800", ctaup="0", dark="0"),
    "dark":  dict(bg="#0b0d12", bg2="#12151c", tx="#eef1f7", mut="#9aa4b6", card="#161a23", line="#242a36",
                  r="18px", sh="0 14px 40px -14px rgba(0,0,0,.7)", bw="1px", hf="system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif",
                  hw="800", ctaup="0", dark="1"),
    "warm":  dict(bg="#fffaf2", bg2="#f6ecdc", tx="#2b2218", mut="#7a6a58", card="#ffffff", line="#ecdfca",
                  r="26px", sh="0 14px 34px -16px rgba(120,80,20,.3)", bw="1px", hf="Georgia,'Times New Roman',serif",
                  hw="700", ctaup="0", dark="0"),
    "bold":  dict(bg="#fffdf3", bg2="#ffe66d", tx="#111111", mut="#3a3a3a", card="#ffffff", line="#111111",
                  r="6px", sh="5px 5px 0 #111", bw="3px", hf="system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif",
                  hw="900", ctaup="1", dark="0"),
}

BASE_CSS = r"""
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--tx);font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;-webkit-text-size-adjust:100%;overflow-x:hidden}
img{max-width:100%;height:auto;display:block}
a{color:inherit}
.w{width:min(1120px,100%);margin:0 auto;padding:0 20px}
h1,h2,h3{font-family:var(--hf);font-weight:var(--hw);letter-spacing:-.02em;margin:0}
h1{font-size:clamp(32px,5.6vw,58px);line-height:1.06}
h2{font-size:clamp(26px,4vw,40px);line-height:1.12;margin-bottom:12px}
h3{font-size:19px;line-height:1.25;margin-bottom:6px}
em{font-style:normal;background:linear-gradient(transparent 62%,color-mix(in srgb,var(--ac) 38%,transparent) 62%);padding:0 .08em;border-radius:3px}
.dark em{background:linear-gradient(transparent 62%,color-mix(in srgb,var(--ac) 55%,transparent) 62%)}
.bold em{background:var(--ac2x);padding:0 .12em;box-decoration-break:clone;-webkit-box-decoration-break:clone}
p{margin:0 0 12px}.mut{color:var(--mut)}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--ac);background:color-mix(in srgb,var(--ac) 11%,transparent);padding:7px 13px;border-radius:99px;margin-bottom:18px}
.bold .eyebrow{background:var(--card);color:var(--tx);border:var(--bw) solid var(--line);box-shadow:3px 3px 0 var(--line)}
.sechead{max-width:680px;margin:0 0 34px}.sechead.c{margin-left:auto;margin-right:auto;text-align:center}
.sechead p{color:var(--mut);font-size:18px}
svg.i{width:1.25em;height:1.25em;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
/* кнопки */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:10px;background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on);font:inherit;font-weight:700;font-size:18px;padding:16px 28px;border:0;border-radius:calc(var(--r) - 4px);cursor:pointer;text-decoration:none;min-height:54px;box-shadow:0 10px 24px -10px var(--ac);transition:transform .15s,box-shadow .15s,filter .15s}
.btn:hover{transform:translateY(-2px);filter:brightness(1.05)}.btn:active{transform:translateY(0)}.btn:disabled{opacity:.6;cursor:wait;transform:none}
.btn.ghost{background:transparent;color:var(--tx);box-shadow:none;border:var(--bw) solid var(--line)}
.bold .btn{background:var(--ac);border:var(--bw) solid #111;box-shadow:5px 5px 0 #111;text-transform:uppercase;letter-spacing:.02em}
.bold .btn:hover{transform:translate(-2px,-2px);box-shadow:7px 7px 0 #111}
.bold .btn:active{transform:translate(3px,3px);box-shadow:2px 2px 0 #111}
.btn.wide{width:100%}
/* шапка */
.top{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(12px);border-bottom:var(--bw) solid var(--line)}
.top .w{display:flex;align-items:center;gap:18px;min-height:64px}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:19px;text-decoration:none}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on);display:grid;place-items:center;font-weight:900;font-size:17px}
.bold .logo{border:var(--bw) solid #111;border-radius:6px}
.nav{display:none;gap:22px;margin-left:auto;font-size:15px;font-weight:600}.nav a{text-decoration:none;color:var(--mut)}.nav a:hover{color:var(--tx)}
.top .tel{margin-left:auto;text-decoration:none;font-weight:700;display:flex;gap:8px;align-items:center;white-space:nowrap}
.top .btn{display:none;padding:10px 18px;min-height:44px;font-size:15px}
@media(min-width:900px){.nav{display:flex}.top .tel{margin-left:0}.top .btn{display:inline-flex}}
@media(max-width:520px){.top .tel span{display:none}.top .tel{width:44px;height:44px;border-radius:50%;background:var(--bg2);justify-content:center}}
/* hero */
.hero{position:relative;padding:48px 0 64px;overflow:hidden;
  background:radial-gradient(900px 520px at 88% -8%,color-mix(in srgb,var(--ac) 24%,transparent),transparent 70%),radial-gradient(700px 420px at -8% 38%,color-mix(in srgb,var(--ac2) 17%,transparent),transparent 70%),var(--bg)}
.bold .hero{background:var(--bg2);border-bottom:var(--bw) solid #111}
.hero .g{display:grid;gap:36px;align-items:center}
@media(min-width:940px){.hero .g{grid-template-columns:1.12fr .88fr;gap:56px}.hero{padding:72px 0 84px}}
.hero p.sub{font-size:clamp(18px,2.2vw,21px);color:var(--mut);margin:18px 0 22px;max-width:560px}
.checks{list-style:none;padding:0;margin:0 0 26px;display:grid;gap:11px}
.checks li{display:flex;gap:12px;align-items:flex-start;font-weight:600}
.checks .ck{width:26px;height:26px;border-radius:50%;background:var(--ac);color:var(--on);display:grid;place-items:center;flex:none;margin-top:1px}
.checks .ck svg{width:15px;height:15px;stroke-width:3}
.bold .checks .ck{border:2px solid #111}
.badges{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}
.badges span{display:inline-flex;gap:8px;align-items:center;font-size:14px;font-weight:600;color:var(--mut);background:var(--card);border:var(--bw) solid var(--line);padding:8px 13px;border-radius:99px}
.bold .badges span{border-radius:6px;color:var(--tx)}
.badges svg{color:var(--ac)}
.cta-row{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
/* форма-картка */
.cf{background:var(--card);border:var(--bw) solid var(--line);border-radius:var(--r);padding:26px;box-shadow:var(--sh);position:relative}
.cf .cf-h{font-family:var(--hf);font-weight:var(--hw);font-size:23px;line-height:1.2;margin-bottom:6px;letter-spacing:-.01em}
.cf .cf-s{color:var(--mut);font-size:15px;margin-bottom:18px}
form.lead{display:grid;gap:13px}
label{font-size:14px;font-weight:700;display:block;margin-bottom:5px}
input[type=text],input[type=tel],input[type=email]{width:100%;font:inherit;padding:14px 15px;border:var(--bw) solid var(--line);border-radius:calc(var(--r) - 6px);background:var(--bg);color:var(--tx);min-height:54px;transition:border-color .15s,box-shadow .15s}
input:focus{outline:0;border-color:var(--ac);box-shadow:0 0 0 4px color-mix(in srgb,var(--ac) 22%,transparent)}
.err{color:#e0364b;font-size:14px;min-height:0}.err:empty{display:none}
.consent{font-size:12.5px;color:var(--mut);line-height:1.45}
.secure{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--mut);margin-top:2px}
.hp{position:absolute;left:-9999px;opacity:0}
/* hero-арт: картинка або плавучі картки */
.art{position:relative}
.art .photo{width:100%;aspect-ratio:4/3.4;object-fit:cover;border-radius:calc(var(--r) + 6px);box-shadow:var(--sh);border:var(--bw) solid var(--line)}
.float{position:absolute;background:var(--card);border:var(--bw) solid var(--line);border-radius:16px;padding:12px 16px;box-shadow:var(--sh);display:flex;gap:11px;align-items:center;font-size:14px;line-height:1.3;max-width:230px}
.float b{display:block;font-size:15px}.float .fi{width:38px;height:38px;border-radius:11px;background:color-mix(in srgb,var(--ac) 16%,transparent);color:var(--ac);display:grid;place-items:center;flex:none}
.float.f1{left:-10px;bottom:34px}.float.f2{right:-8px;top:26px}
@media(max-width:939px){.float.f1{left:8px;bottom:-16px}.float.f2{right:8px;top:-14px}.art{margin:14px 0 10px}}
.blob{position:absolute;inset:auto;width:70%;aspect-ratio:1;border-radius:50%;filter:blur(40px);opacity:.5;background:linear-gradient(135deg,var(--ac),var(--ac2));right:-8%;top:-10%;z-index:0}
.art>*:not(.float):not(.blob){position:relative;z-index:1}.float{z-index:2}
/* смуга цифр */
.stats{background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on)}
.bold .stats{background:#111;color:#fff;border-bottom:var(--bw) solid #111}
.stats .w{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:20px;padding-top:34px;padding-bottom:34px;text-align:center}
.stats b{display:block;font-family:var(--hf);font-size:clamp(30px,4.5vw,46px);line-height:1;font-weight:var(--hw);letter-spacing:-.02em}
.stats span{font-size:14px;opacity:.9;display:block;margin-top:8px}
/* секції */
section{padding:72px 0}section.alt{background:var(--bg2)}
@media(max-width:700px){section{padding:52px 0}}
.grid{display:grid;gap:18px}@media(min-width:760px){.grid.c2{grid-template-columns:repeat(2,1fr)}.grid.c3{grid-template-columns:repeat(3,1fr)}}
.card{background:var(--card);border:var(--bw) solid var(--line);border-radius:var(--r);padding:26px;box-shadow:var(--sh);transition:transform .2s}
.card:hover{transform:translateY(-3px)}
.bold .card:hover{transform:translate(-2px,-2px);box-shadow:8px 8px 0 #111}
.ico{width:50px;height:50px;border-radius:14px;background:color-mix(in srgb,var(--ac) 15%,transparent);color:var(--ac);display:grid;place-items:center;margin-bottom:16px}
.ico svg{width:26px;height:26px}
.bold .ico{background:var(--ac);color:var(--on);border:var(--bw) solid #111;border-radius:8px}
.card p{color:var(--mut);margin:0}
/* болі */
.pains{display:grid;gap:12px;max-width:760px}
.pain{display:flex;gap:14px;align-items:flex-start;background:var(--card);border:var(--bw) solid var(--line);padding:16px 18px;border-radius:calc(var(--r) - 4px);font-weight:600}
.pain .x{width:28px;height:28px;border-radius:50%;background:#fde7ea;color:#e0364b;display:grid;place-items:center;flex:none}
.dark .pain .x{background:#3a1820}.pain .x svg{width:15px;height:15px;stroke-width:3}
.bridge{margin-top:26px;font-size:20px;font-weight:700;display:flex;gap:10px;align-items:center;color:var(--ac)}
/* кроки */
.steps{counter-reset:s;display:grid;gap:18px;position:relative}
@media(min-width:860px){.steps.n3{grid-template-columns:repeat(3,1fr)}.steps.n4{grid-template-columns:repeat(4,1fr)}.steps.n2{grid-template-columns:repeat(2,1fr)}}
.step{counter-increment:s;position:relative;background:var(--card);border:var(--bw) solid var(--line);border-radius:var(--r);padding:26px 24px;box-shadow:var(--sh)}
.step:before{content:counter(s);display:grid;place-items:center;width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on);font-weight:800;font-size:19px;margin-bottom:16px}
.bold .step:before{background:var(--ac);border:var(--bw) solid #111;border-radius:6px}
.step p{color:var(--mut);margin:0}
@media(min-width:860px){.step:not(:last-child):after{content:"";position:absolute;top:46px;left:calc(100% - 4px);width:26px;border-top:2px dashed var(--line)}}
/* відгуки */
.rev{display:flex;flex-direction:column;gap:14px}.rev .q{font-size:17px;line-height:1.55;margin:0;color:var(--tx)}
.rev .q:before{content:"\201C";display:block;font-family:Georgia,serif;font-size:60px;line-height:.5;color:var(--ac);margin-bottom:8px}
.who{display:flex;gap:12px;align-items:center;margin-top:auto}
.av{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on);display:grid;place-items:center;font-weight:800}
.who b{display:block;line-height:1.2}.who small{color:var(--ac);font-weight:700}
/* акція */
.offer{border-radius:calc(var(--r) + 6px);padding:clamp(28px,5vw,52px);background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on);display:grid;gap:22px;align-items:center;position:relative;overflow:hidden}
.offer:before{content:"";position:absolute;width:340px;height:340px;border-radius:50%;background:rgba(255,255,255,.14);right:-90px;top:-130px}
.bold .offer{background:var(--ac);color:#111;border:var(--bw) solid #111;box-shadow:8px 8px 0 #111}
@media(min-width:800px){.offer{grid-template-columns:1.4fr auto}}
.offer h2{margin-bottom:8px}.offer p{margin:0;opacity:.95;font-size:18px}
.offer .btn{background:var(--on);color:var(--ac);box-shadow:none;position:relative}
.bold .offer .btn{background:#111;color:#fff;border-color:#111}
/* faq */
.faq{max-width:820px;display:grid;gap:12px}
details{background:var(--card);border:var(--bw) solid var(--line);border-radius:calc(var(--r) - 4px);padding:0;overflow:hidden}
summary{cursor:pointer;font-weight:700;padding:18px 54px 18px 20px;list-style:none;position:relative;font-size:18px}
summary::-webkit-details-marker{display:none}
summary:after{content:"+";position:absolute;right:20px;top:50%;transform:translateY(-50%);font-size:26px;font-weight:400;color:var(--ac);transition:transform .2s}
details[open] summary:after{transform:translateY(-50%) rotate(45deg)}
details p{padding:0 20px 18px;margin:0;color:var(--mut)}
/* фінальна дія */
.final{background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on)}
.bold .final{background:var(--ac);color:#111;border-top:var(--bw) solid #111}
.final .g{display:grid;gap:34px;align-items:center}@media(min-width:900px){.final .g{grid-template-columns:1fr 1fr;gap:60px}}
.final h2{font-size:clamp(28px,4.4vw,44px)}.final p{font-size:19px;opacity:.95}
.final .cf{color:var(--tx)}
.contactline{display:flex;flex-wrap:wrap;gap:12px 22px;margin-top:22px;font-weight:700}
.contactline a{display:inline-flex;gap:8px;align-items:center;text-decoration:none}
footer{padding:36px 0 96px;font-size:14px;color:var(--mut);border-top:var(--bw) solid var(--line)}
footer p{margin:0 0 8px}
.sticky{position:fixed;left:0;right:0;bottom:0;padding:10px 14px calc(10px + env(safe-area-inset-bottom));background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(10px);border-top:var(--bw) solid var(--line);z-index:15;display:none}
.sticky .btn{width:100%}@media(max-width:759px){.sticky{display:block}}
.demo{background:#ffedb3;color:#5a4300;text-align:center;font-size:13px;padding:6px}
.hide{display:none}
/* квіз */
.qpage{min-height:100vh;display:grid;background:radial-gradient(900px 600px at 100% 0,color-mix(in srgb,var(--ac) 22%,transparent),transparent 70%),radial-gradient(700px 500px at 0 100%,color-mix(in srgb,var(--ac2) 16%,transparent),transparent 70%),var(--bg2)}
.bold .qpage{background:var(--bg2)}
.qm{display:grid;gap:26px;align-items:center;padding:30px 20px 60px;width:min(1120px,100%);margin:0 auto}
@media(min-width:940px){.qm{grid-template-columns:1fr 1.08fr;gap:56px;padding-top:50px}}
.qside h1{font-size:clamp(30px,4.6vw,48px);margin-bottom:14px}
.qside p.sub{font-size:19px;color:var(--mut);margin-bottom:20px}
.qextra{display:none}
@media(max-width:939px){.dsk{display:none}.qextra{display:block}.qside p.sub{margin-bottom:0}}
.mgr{display:flex;gap:14px;align-items:center;background:var(--card);border:var(--bw) solid var(--line);border-radius:var(--r);padding:14px 16px;margin-top:22px;box-shadow:var(--sh);max-width:430px}
.mgr .av{width:52px;height:52px;font-size:20px}.mgr small{color:var(--mut);display:block}
.bonus{display:flex;gap:14px;align-items:center;background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on);border-radius:var(--r);padding:16px 18px;margin-top:22px;max-width:430px}
.bold .bonus{background:var(--ac);color:#111;border:var(--bw) solid #111;box-shadow:var(--sh)}
.bonus svg{width:30px;height:30px}.bonus b{display:block}.bonus span{font-size:14px;opacity:.95}
.qcard{background:var(--card);border:var(--bw) solid var(--line);border-radius:calc(var(--r) + 6px);padding:clamp(22px,4vw,38px);box-shadow:var(--sh)}
.qtop{display:flex;justify-content:space-between;align-items:center;font-size:14px;font-weight:700;color:var(--mut);margin-bottom:10px}
.bar{height:10px;background:var(--bg2);border-radius:99px;overflow:hidden;margin:0 0 26px;border:var(--bw) solid var(--line)}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--ac),var(--ac2));width:0;transition:width .35s;border-radius:99px}
#qbox{animation:in .28s}@keyframes in{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:none}}
#qbox h2{font-size:clamp(24px,3.4vw,32px);margin-bottom:20px}
.opts{display:grid;gap:12px}@media(min-width:560px){.opts.two{grid-template-columns:1fr 1fr}}
.opt{display:flex;gap:14px;align-items:center;width:100%;text-align:left;font:inherit;font-weight:600;background:var(--bg);color:var(--tx);border:var(--bw) solid var(--line);border-radius:calc(var(--r) - 4px);padding:15px 16px;cursor:pointer;min-height:62px;transition:border-color .15s,transform .15s,box-shadow .15s}
.opt:hover{border-color:var(--ac);transform:translateY(-2px);box-shadow:0 8px 20px -12px var(--ac)}
.opt .l{width:34px;height:34px;border-radius:10px;background:color-mix(in srgb,var(--ac) 14%,transparent);color:var(--ac);display:grid;place-items:center;font-weight:800;flex:none}
.bold .opt .l{background:var(--ac);color:var(--on);border:2px solid #111;border-radius:6px}
.opt.on{border-color:var(--ac);background:color-mix(in srgb,var(--ac) 10%,var(--bg))}
.back{background:none;border:0;color:var(--mut);cursor:pointer;font:inherit;font-weight:600;padding:12px 0 0;margin-top:8px}
.unlock{display:flex;gap:12px;align-items:center;background:color-mix(in srgb,var(--ac) 12%,transparent);color:var(--tx);border-radius:14px;padding:12px 14px;font-weight:600;margin-bottom:16px;font-size:15px}
.unlock svg{color:var(--ac);width:24px;height:24px}
/* подяка */
.ty{min-height:70vh;display:grid;place-items:center;padding:60px 20px;text-align:center}
.ty .tick{width:84px;height:84px;border-radius:50%;background:linear-gradient(135deg,var(--ac),var(--ac2));color:var(--on);display:grid;place-items:center;margin:0 auto 24px;animation:pop .5s}
.bold .ty .tick{border:var(--bw) solid #111;box-shadow:var(--sh)}
.ty .tick svg{width:42px;height:42px;stroke-width:3}@keyframes pop{from{transform:scale(.4);opacity:0}to{transform:none;opacity:1}}
.ty .next{max-width:520px;margin:28px auto 0;text-align:left;display:grid;gap:12px}
.ty .next div{display:flex;gap:14px;align-items:flex-start;background:var(--card);border:var(--bw) solid var(--line);border-radius:14px;padding:14px 16px}
.ty .next b.n{width:30px;height:30px;border-radius:50%;background:var(--ac);color:var(--on);display:grid;place-items:center;flex:none;font-size:15px}
"""

ICONS = {
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "star": '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "pin": '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    "gift": '<rect x="3" y="8" width="18" height="4"/><path d="M12 8v13M19 12v9H5v-9M7.5 8a2.5 2.5 0 0 1 0-5C11 3 12 8 12 8s1-5 4.5-5a2.5 2.5 0 0 1 0 5"/>',
    "heart": '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    "chart": '<path d="M18 20V10M12 20V4M6 20v-6"/>',
    "tool": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z"/>',
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>',
    "arrow": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "send": '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
}
ICON_CYCLE = ["bolt", "users", "shield", "chart", "heart", "clock", "tool", "star", "chat"]

def ic(name, cls="i"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICONS.get(name, ICONS["check"])}</svg>'

# ---------------------------------------------------------------- JS
PIXEL = """!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');fbq('init','__PID__');fbq('track','PageView');"""

JS_COMMON = r"""
(function(){
var P=__CFG__;
function uid(){try{var k=sessionStorage.getItem('eid');if(!k){k=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random().toString(16).slice(2));sessionStorage.setItem('eid',k)}return k}catch(e){return String(Date.now())}}
var Q=new URLSearchParams(location.search),U={};
['utm_source','utm_medium','utm_campaign','utm_content','utm_term','fbclid','ad_id','adset_id','campaign_id','placement'].forEach(function(k){var v=Q.get(k);if(v){U[k]=v;try{sessionStorage.setItem('u_'+k,v)}catch(e){}}else{try{var s=sessionStorage.getItem('u_'+k);if(s)U[k]=s}catch(e){}}});
function track(n,d){if(window.fbq)fbq('trackCustom',n,d||{})}
function fixPhone(v){var d=String(v).replace(/\D/g,'');if(d.indexOf('380')===0)d=d.slice(3);else if(d.charAt(0)==='0')d=d.slice(1);return d.length===9?'+380'+d:null}
function send(fields,btn,err){
  var eid=uid(),ph=fixPhone(fields.phone||'');
  if(!ph){err.textContent='Введіть номер у форматі 0XX XXX XX XX';return}
  if(fields.website){return}
  fields.phone=ph;err.textContent='';btn.disabled=true;
  var body=new URLSearchParams();for(var k in fields)body.append(k,fields[k]);
  for(var u in U)body.append(u,U[u]);
  body.append('event_id',eid);body.append('page',location.pathname);body.append('ts',new Date().toISOString());
  var go=function(){location.href=P.thanks+'?eid='+encodeURIComponent(eid)};
  if(!P.endpoint){console.log('DEMO lead',Object.fromEntries(body));setTimeout(go,300);return}
  var done=false,t=setTimeout(function(){if(!done){done=true;go()}},4000);
  fetch(P.endpoint,{method:'POST',mode:'no-cors',body:body}).then(function(){if(!done){done=true;clearTimeout(t);go()}}).catch(function(){btn.disabled=false;err.textContent='Не вдалося надіслати. Спробуйте ще раз або зателефонуйте.'});
}
window.__lead=send;window.__track=track;window.__U=U;
document.querySelectorAll('[data-go]').forEach(function(a){a.addEventListener('click',function(){track('CtaClick',{where:a.getAttribute('data-go')})})});
document.querySelectorAll('form.lead').forEach(function(f){f.addEventListener('submit',function(e){e.preventDefault();var d={};new FormData(f).forEach(function(v,k){d[k]=v});send(d,f.querySelector('button[type=submit]'),f.querySelector('.err'))})});
var st=document.querySelector('.sticky');
if(st&&'IntersectionObserver'in window){var vis=0;var io=new IntersectionObserver(function(en){en.forEach(function(x){vis+=x.isIntersecting?1:-1});st.style.display=vis>0?'none':''});document.querySelectorAll('.cf').forEach(function(x){io.observe(x)})}
})();
"""

JS_QUIZ = r"""
(function(){
var Z=__QUIZ__,End=__END__,i=0,ans=[],lock=false,box=document.getElementById('qbox'),bar=document.getElementById('qbar'),lab=document.getElementById('qlab'),started=false,n=Z.length;
var L='ABCDEFGH';
function set(p,t){bar.style.width=p+'%';lab.textContent=t}
function step(){
  box.style.animation='none';box.offsetHeight;box.style.animation='';
  if(i>=n)return contact();
  set(Math.round(i/(n+1)*100),'Питання '+(i+1)+' з '+n);
  var q=Z[i],h='<h2>'+q.q+'</h2><div class="opts'+(q.options.length<=4&&q.options.every(function(o){return o.length<28})?' two':'')+'">';
  q.options.forEach(function(o,k){h+='<button type="button" class="opt" data-k="'+k+'"><span class="l">'+L.charAt(k)+'</span><span>'+o+'</span></button>'});
  h+='</div>';if(i>0)h+='<button type="button" class="back">← Назад</button>';
  box.innerHTML=h;
  box.querySelectorAll('.opt').forEach(function(b){b.addEventListener('click',function(){
    if(lock)return;lock=true;
    if(!started){started=true;window.__track('QuizStart')}
    b.classList.add('on');ans[i]={q:q.q,a:q.options[+b.dataset.k]};window.__track('QuizStep',{step:i+1});
    setTimeout(function(){lock=false;i++;step()},170)})});
  var bk=box.querySelector('.back');if(bk)bk.addEventListener('click',function(){i--;step()});
}
function contact(){
  set(92,'Останній крок');
  box.innerHTML='<div class="unlock">'+End.icon+'<span>'+End.unlock+'</span></div><h2>'+End.t+'</h2><p class="mut">'+End.d+'</p><form id="qf" class="lead" novalidate><div><label>Ім’я</label><input type="text" name="name" required autocomplete="given-name"></div><div><label>Телефон</label><input type="tel" name="phone" required autocomplete="tel" placeholder="0XX XXX XX XX" inputmode="tel"></div><input class="hp" type="text" name="website" tabindex="-1" autocomplete="off"><button class="btn wide" type="submit">'+End.b+'</button><div class="err"></div><div class="consent">'+End.c+'</div></form><button type="button" class="back">← Назад</button>';
  box.querySelector('.back').addEventListener('click',function(){i--;step()});
  var f=box.querySelector('#qf');
  f.addEventListener('submit',function(e){e.preventDefault();var d={};new FormData(f).forEach(function(v,k){d[k]=v});
    d.quiz=ans.map(function(x){return x.q+': '+x.a}).join(' | ');window.__lead(d,f.querySelector('button[type=submit]'),f.querySelector('.err'))});
}
step();
})();
"""

THANKS_JS = """(function(){var q=new URLSearchParams(location.search),eid=q.get('eid');
__PIXEL__
if(window.fbq){fbq('track','Lead',{},eid?{eventID:eid}:{})}
})();"""

# ---------------------------------------------------------------- допоміжне
def need(b, path):
    cur = b
    for p in path.split('.'):
        if not isinstance(cur, dict) or p not in cur or cur[p] in ("", None, []):
            return None
        cur = cur[p]
    return cur

def tg_link(v):
    """t.me/name, @name або name -> повне https://t.me/name; готове посилання лишаємо."""
    v = str(v).strip()
    if re.match(r"^https?://", v): return v
    if v.startswith("@"): return "https://t.me/" + v[1:]
    if re.match(r"^(t\.me|telegram\.me)/", v): return "https://" + v
    return "https://t.me/" + v

def fix_url(v):
    """Лише додає https:// до t.me/... і tel:/mailto: залишає; решту не чіпає."""
    v = str(v).strip()
    if re.match(r"^(t\.me|telegram\.me)/", v): return "https://" + v
    return v

def pixel_snippet(b):
    pid = (b.get("tracking") or {}).get("pixel_id", "")
    if pid and not re.fullmatch(r"\d{8,20}", str(pid)):
        sys.exit("pixel_id має бути числом (зазвичай 15-16 цифр, допускається 8-20), без букв.")
    return PIXEL.replace("__PID__", str(pid)) if pid else ""

def cta(b, where, target="#order", label=None, cls=""):
    lab = label or b.get("hero", {}).get("cta") or b["form"]["button"]
    return f'<a class="btn {cls}" href="{target}" data-go="{where}">{E(lab)}{ic("arrow")}</a>'

def form_html(b, fid=None, note=True):
    f = b["form"]
    fields = f.get("fields", ["name", "phone"])
    rows = ""
    if "name" in fields:
        rows += '<div><label>Ім’я</label><input type="text" name="name" required autocomplete="given-name"></div>'
    rows += '<div><label>Телефон</label><input type="tel" name="phone" required autocomplete="tel" placeholder="0XX XXX XX XX" inputmode="tel"></div>'
    if "comment" in fields:
        rows += '<div><label>Що вас цікавить</label><input type="text" name="comment"></div>'
    idattr = f' id="{fid}"' if fid else ""
    # рядок під формою береться ЛИШЕ з брифу (form.secure): жодних тверджень про клієнта, яких він не давав
    sec = f'<div class="secure">{ic("lock")}<span>{E(f["secure"])}</span></div>' if (note and f.get("secure")) else ""
    return (f'<form{idattr} class="lead" novalidate>{rows}<input class="hp" type="text" name="website" tabindex="-1" autocomplete="off">'
            f'<button class="btn wide" type="submit">{E(f["button"])}{ic("arrow")}</button><div class="err"></div>'
            f'<div class="consent">{E(f["consent"])}</div>{sec}</form>')

def form_card(b, fid=None, title=None, sub=None):
    f = b["form"]
    sub = sub or f.get("subtitle")
    idattr = ' id="form"' if fid else ""
    subhtml = f'<div class="cf-s">{E(sub)}</div>' if sub else ""
    return f'<div class="cf"{idattr}><div class="cf-h">{E(title or f["title"])}</div>{subhtml}{form_html(b, fid)}</div>'

def footer(b):
    c = b.get("contact", {}); l = b.get("legal", {})
    parts = []
    if l.get("company"): parts.append(E(l["company"]))
    if c.get("address"): parts.append(E(c["address"]))
    if c.get("hours"): parts.append(E(c["hours"]))
    priv = f'<p>{E(l["privacy_text"])}</p>' if l.get("privacy_text") else ""
    return f'<footer><div class="w"><p>{" · ".join(parts)}</p>{priv}</div></footer>'

def top(b, nav=True):
    c = b.get("contact", {})
    tel = c.get("phone", "")
    lg = b.get("logo")
    mark = f'<img src="{E(lg)}" alt="" width="34" height="34" style="border-radius:10px">' if lg else f'<span class="logo">{E(b["brand"][:1].upper())}</span>'
    links = ""
    if nav:
        items = [("#benefits", "Переваги", "benefits"), ("#steps", "Як це працює", "steps"), ("#faq", "Питання", "faq")]
        links = '<nav class="nav">' + "".join(f'<a href="{h}">{t}</a>' for h, t, k in items if b.get(k)) + '</nav>'
    t = f'<a class="tel" href="tel:{E(re.sub(r"[^+0-9]", "", tel))}">{ic("phone")}<span>{E(tel)}</span></a>' if tel else ""
    btn = cta(b, "top", label=b["form"]["button"]) if nav else ""
    return f'<header class="top"><div class="w"><a class="brand" href="#">{mark}<span>{E(b["brand"])}</span></a>{links}{t}{btn}</div></header>'

def head(b, title, desc, css):
    return (f'<!doctype html><html lang="{E(b.get("lang","uk"))}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(title)}</title>'
            f'<meta name="description" content="{E(desc)}"><meta name="robots" content="noindex">'
            f'<meta name="theme-color" content="{E(b.get("accent","#2563eb"))}"><style>{css}</style></head>')

# ---------------------------------------------------------------- секції лендингу
def sec_head(title, sub="", center=False):
    return f'<div class="sechead{" c" if center else ""}"><h2>{emph(title)}</h2>' + (f'<p>{E(sub)}</p>' if sub else '') + '</div>'

def build_hero(b):
    h = b["hero"]; f = b["form"]
    bullets = "".join(f'<li><span class="ck">{ic("check")}</span><span>{E(x)}</span></li>' for x in h.get("bullets", []))
    bullets = f'<ul class="checks">{bullets}</ul>' if bullets else ""
    badges = "".join(f'<span>{ic(x.get("icon", "shield") if isinstance(x, dict) else "shield")}{E(x["t"] if isinstance(x, dict) else x)}</span>' for x in h.get("badges", []))
    badges = f'<div class="badges">{badges}</div>' if badges else ""
    img = h.get("image")
    floats = ""
    for k, x in enumerate(h.get("floats", [])[:2]):
        floats += f'<div class="float f{k+1}"><span class="fi">{ic(x.get("icon", "star"))}</span><div><b>{E(x["t"])}</b>{E(x.get("d", ""))}</div></div>'
    layout = h.get("layout", "form")
    if layout == "image" and img:
        art = (f'<div class="art"><div class="blob"></div><img class="photo" src="{E(img)}" alt="{E(h.get("image_alt", b["brand"]))}" width="900" height="760" fetchpriority="high">{floats}</div>')
        right = art
        below = ""
    else:
        photo = (f'<img class="photo" style="margin-bottom:18px;aspect-ratio:16/9" src="{E(img)}" alt="{E(h.get("image_alt", b["brand"]))}" width="900" height="500" fetchpriority="high">' if img else "")
        right = f'<div class="art"><div class="blob"></div>{photo}{form_card(b, "lead", f["title"], f.get("subtitle"))}</div>'
    eyebrow = f'<span class="eyebrow">{E(h["eyebrow"])}</span>' if h.get("eyebrow") else ""
    target = "#form" if layout != "image" else "#order"
    return (f'<section class="hero"><div class="w"><div class="g"><div>{eyebrow}'
            f'<h1>{emph(h["h1"])}</h1><p class="sub">{E(h["sub"])}</p>{bullets}'
            f'<div class="cta-row">{cta(b, "hero", target, h.get("cta"))}</div>{badges}</div>{right}</div></div></section>')

def sec_stats(b):
    d = (b.get("proof") or {}).get("numbers")
    if not d: return ""
    return '<div class="stats"><div class="w">' + "".join(f'<div><b>{E(x["v"])}</b><span>{E(x["l"])}</span></div>' for x in d) + '</div></div>'

def sec_pains(b):
    d = b.get("pains")
    if not d: return ""
    items = "".join(f'<div class="pain"><span class="x">{ic("x")}</span><span>{E(x)}</span></div>' for x in d["items"])
    bridge = f'<div class="bridge">{ic("arrow")}{E(d["bridge"])}</div>' if d.get("bridge") else ""
    return f'<section class="alt"><div class="w">{sec_head(d["title"], d.get("sub", ""))}<div class="pains">{items}</div>{bridge}</div></section>'

def sec_benefits(b):
    d = b.get("benefits")
    if not d: return ""
    n = len(d["items"]); cls = "c3" if n % 3 == 0 else "c2"
    cards = ""
    for k, x in enumerate(d["items"]):
        cards += f'<div class="card"><div class="ico">{ic(x.get("icon") or ICON_CYCLE[k % len(ICON_CYCLE)])}</div><h3>{E(x["t"])}</h3><p>{E(x["d"])}</p></div>'
    return f'<section id="benefits"><div class="w">{sec_head(d["title"], d.get("sub", ""))}<div class="grid {cls}">{cards}</div></div></section>'

def sec_steps(b):
    d = b.get("steps")
    if not d: return ""
    n = len(d["items"])
    cards = "".join(f'<div class="step"><h3>{E(x["t"])}</h3><p>{E(x["d"])}</p></div>' for x in d["items"])
    return f'<section id="steps" class="alt"><div class="w">{sec_head(d["title"], d.get("sub", ""))}<div class="steps n{min(n,4)}">{cards}</div></div></section>'

def sec_proof(b):
    d = b.get("proof")
    if not d or not d.get("items"): return ""
    cards = ""
    for x in d["items"]:
        ini = "".join(w[0] for w in x["name"].split()[:2]).upper()
        cards += (f'<div class="card rev"><p class="q">{E(x["text"])}</p><div class="who"><span class="av">{E(ini)}</span><div><b>{E(x["name"])}</b>'
                  + (f'<small>{E(x["result"])}</small>' if x.get("result") else "") + '</div></div></div>')
    n = len(d["items"]); cls = "c3" if n % 3 == 0 else "c2"
    return f'<section><div class="w">{sec_head(d["title"], d.get("sub", ""))}<div class="grid {cls}">{cards}</div></div></section>'

def sec_offer(b):
    o = b.get("offer")
    if not o: return ""
    return (f'<section style="padding:0 0 72px"><div class="w"><div class="offer"><div><h2>{emph(o["title"])}</h2><p>{E(o["text"])}</p></div>'
            f'{cta(b, "offer", label=o.get("button", b["form"]["button"]))}</div></div></section>')

def sec_faq(b):
    d = b.get("faq")
    if not d: return ""
    items = "".join(f'<details><summary>{E(x["q"])}</summary><p>{E(x["a"])}</p></details>' for x in d)
    return f'<section id="faq" class="alt"><div class="w">{sec_head("Часті **запитання**")}<div class="faq">{items}</div></div></section>'

def sec_final(b):
    f = b["form"]; c = b.get("contact", {}); fin = b.get("final", {})
    cl = ""
    if c.get("phone"): cl += f'<a href="tel:{E(re.sub(r"[^+0-9]", "", c["phone"]))}">{ic("phone")}{E(c["phone"])}</a>'
    if c.get("telegram"): cl += f'<a href="{E(tg_link(c["telegram"]))}">{ic("send")}Telegram</a>'
    cl = f'<div class="contactline">{cl}</div>' if cl else ""
    return (f'<section class="final" id="order"><div class="w"><div class="g"><div><h2>{emph(fin.get("title", f["title"]))}</h2>'
            f'<p>{E(fin.get("text", ""))}</p>{cl}</div>{form_card(b, None, f["title"], f.get("subtitle"))}</div></div></section>')

def build_landing(b):
    return (build_hero(b) + sec_stats(b) + sec_pains(b) + sec_benefits(b) + sec_steps(b) + sec_proof(b)
            + sec_offer(b) + sec_faq(b) + sec_final(b))

# ---------------------------------------------------------------- квіз
def build_quiz(b):
    z = b["quiz"]; c = b.get("contact", {})
    side = "".join(f'<li><span class="ck">{ic("check")}</span><span>{E(x)}</span></li>' for x in z.get("side", []))
    side = f'<ul class="checks">{side}</ul>' if side else ""
    mg = z.get("manager")
    mgr = ""
    if mg:
        mgr = (f'<div class="mgr"><span class="av">{E(mg["name"][:1].upper())}</span><div><b>{E(mg["name"])}</b>'
               f'<small>{E(mg.get("role", ""))}</small><span style="font-size:14px">{E(mg.get("text", ""))}</span></div></div>')
    bn = z.get("bonus")
    bonus = f'<div class="bonus">{ic("gift")}<div><b>{E(bn["title"])}</b><span>{E(bn["text"])}</span></div></div>' if bn else ""
    mark = f'<span class="logo">{E(b["brand"][:1].upper())}</span>'
    extra = f'{side}{bonus}{mgr}'
    return (f'<div class="qpage"><div class="qm"><div class="qside"><a class="brand" href="#" style="margin-bottom:26px;display:flex">{mark}<span>{E(b["brand"])}</span></a>'
            + (f'<span class="eyebrow">{E(z["eyebrow"])}</span>' if z.get("eyebrow") else "")
            + f'<h1>{emph(z["title"])}</h1><p class="sub">{E(z["intro"])}</p><div class="dsk">{extra}</div></div>'
            f'<div class="qcard"><div class="qtop"><span id="qlab"></span><span>~1 хв</span></div><div class="bar"><i id="qbar"></i></div><div id="qbox"></div></div>'
            f'<div class="qextra">{extra}</div></div></div>')

# ---------------------------------------------------------------- збірка
def theme_css(b):
    th = THEMES.get(b.get("style", "fresh"), THEMES["fresh"]).copy()
    ac = b.get("accent", "#2563eb")
    ac2 = b.get("accent2") or shift(ac, 0.07, 0.0)
    v = dict(th); v.update(ac=ac, ac2=ac2, on=on_color(ac), ac2x=ac2)
    if b.get("style") == "bold": v["ac2x"] = shift(ac, 0.0, 0.18)
    root = ":root{" + ";".join(f"--{k}:{val}" for k, val in v.items() if k not in ("ctaup", "dark")) + "}"
    return root + BASE_CSS, th

def build(b, out):
    css, th = theme_css(b)
    fmt = b.get("format", "landing")
    cls = ("dark " if th["dark"] == "1" else "") + ("bold" if b.get("style") == "bold" else "")
    trk = b.get("tracking", {})
    cfg = json.dumps({"endpoint": trk.get("endpoint", ""), "thanks": trk.get("thanks_url", "thanks.html")}, ensure_ascii=False)
    px = pixel_snippet(b)
    demo = '' if trk.get("endpoint") else '<div class="demo">ДЕМО-РЕЖИМ: заявки нікуди не відправляються (endpoint не задано)</div>'
    if fmt == "quiz":
        z = b["quiz"]
        body = build_quiz(b)
        end = json.dumps({"t": z["end_title"], "d": z["end_text"], "b": b["form"]["button"], "c": b["form"]["consent"],
                          "unlock": z.get("unlock", "Розрахунок готовий. Залишилось вказати, куди його надіслати."),
                          "icon": ic("gift")}, ensure_ascii=False)
        qs = json.dumps([{"q": x["q"], "options": x["options"]} for x in z["questions"]], ensure_ascii=False)
        js = JS_COMMON.replace("__CFG__", cfg) + JS_QUIZ.replace("__QUIZ__", qs).replace("__END__", end)
        sticky = ""
        header = ""
        title = z["title"].replace("**", "")
        desc = b.get("seo_desc") or z["intro"]
        foot = footer(b)
    else:
        body = build_landing(b)
        js = JS_COMMON.replace("__CFG__", cfg)
        sticky = f'<div class="sticky">{cta(b, "sticky")}</div>'
        header = top(b)
        title = (b.get("seo_title") or b["hero"]["h1"]).replace("**", "")
        desc = b.get("seo_desc") or b["hero"]["sub"]
        foot = footer(b)
    page = (head(b, title, desc, css) + f'<body class="{cls.strip()}">' + demo + header + body + foot + sticky
            + f"<script>{px}</script><script>{js}</script></body></html>")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "index.html"), "w", encoding="utf8").write(page)
    # сторінка подяки
    t = b.get("thanks", {})
    nxt = ""
    for k, x in enumerate(t.get("next", []), 1):
        nxt += f'<div><b class="n">{k}</b><span>{E(x)}</span></div>'
    nxt = f'<div class="next">{nxt}</div>' if nxt else ""
    tbtn = (f'<p style="margin-top:26px"><a class="btn" href="{E(fix_url(t["button_url"]))}">{E(t.get("button", "Написати в Telegram"))}{ic("send")}</a></p>' if t.get("button_url") else "")
    tbody = (f'<main class="ty"><div><div class="tick">{ic("check")}</div><h1 style="font-size:clamp(28px,5vw,44px)">{E(t.get("title", "Дякуємо! Заявку отримано"))}</h1>'
             f'<p class="mut" style="font-size:19px;max-width:520px;margin:14px auto 0">{E(t.get("text", "Ми зв’яжемося з вами найближчим часом."))}</p>{nxt}{tbtn}</div></main>')
    tp = (head(b, "Дякуємо", "", css) + f'<body class="{cls.strip()}">' + top(b, nav=False) + tbody
          + f"<script>{THANKS_JS.replace('__PIXEL__', px)}</script></body></html>")
    open(os.path.join(out, "thanks.html"), "w", encoding="utf8").write(tp)
    src = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "img")
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(out, "img"), dirs_exist_ok=True)
    # lead_endpoint.gs у out/ НЕ копіюємо: out/ публікується на хостинг, а скрипт приймача лише для Google Apps Script
    return len(page.encode("utf8"))

def validate(b):
    errs = []
    fmt = b.get("format", "landing")
    if b.get("style", "fresh") not in THEMES:
        errs.append("style має бути одним із: " + ", ".join(THEMES))
    if b.get("accent") and not re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", b["accent"]):
        errs.append("accent має бути кольором #rrggbb")
    for p in ["brand", "form.title", "form.button", "form.consent"]:
        if not need(b, p): errs.append("порожнє поле: " + p)
    if fmt == "landing":
        for p in ["hero.h1", "hero.sub"]:
            if not need(b, p): errs.append("порожнє поле: " + p)
    else:
        for p in ["quiz.title", "quiz.intro", "quiz.questions", "quiz.end_title", "quiz.end_text"]:
            if not need(b, p): errs.append("порожнє поле: " + p)
    blob = json.dumps(b, ensure_ascii=False)
    if re.search(r"(\[\.\.\.\]|TODO|ЗАПОВНИ|lorem|Lorem|XXX)", blob):
        errs.append("у брифі лишились заглушки (TODO/XXX/...)")
    if fmt == "landing" and b.get("hero", {}).get("h1") and len(b["hero"]["h1"].replace("**", "")) > 90:
        errs.append("заголовок H1 задовгий (понад 90 символів)")
    return errs

if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):  # кирилиця у виводі на Windows
        try: _s.reconfigure(encoding="utf-8")
        except Exception: pass
    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    b = json.load(open(a.brief, encoding="utf-8-sig"))
    e = validate(b)
    if e:
        print("Бриф не пройшов перевірку:"); [print(" -", x) for x in e]; sys.exit(1)
    size = build(b, a.out)
    print(f"Готово: {a.out}/index.html ({size/1024:.1f} КБ), {a.out}/thanks.html")
