# -*- coding: utf-8 -*-
"""Пошук і завантаження перебивок зі СТОКІВ з вільною ліцензією через їхні офіційні API (Pexels, Pixabay).

Два способи, ключі не обов'язкові:
  1. БЕЗ КЛЮЧІВ (основний): агент сам знаходить кадр на сайті зі вільною ліцензією (Mixkit, Pexels, Pixabay: браузер, пошук), показує
     користувачу сторінку кліпа, отримує згоду й додає прямий файл командою `add` (нижче). Не YouTube і не масовий парсинг.
  2. З ключем (необов'язково): офіційні API Pexels/Pixabay, команди `search` і `get`.
     PEXELS_API_KEY (pexels.com/api), PIXABAY_API_KEY (pixabay.com/api/docs): лише змінними середовища, у чат не вставляти.

  python fetch_stock.py add --source mixkit|pexels|pixabay --url <пряме посилання на файл .mp4/.jpg> --page <сторінка кліпа> [--author "…"] --yes
      завантажує ОДИН файл, який вказав агент (адреса має бути на дозволеному CDN), у <VM_ROOT>/library/stock/ і дописує в library/catalog.json
      (джерело, ліцензія, сторінка). Далі: library_catalog.py scan і describe. `--yes` лише після згоди користувача.

  python fetch_stock.py search --source pexels|pixabay --query "counting cash" [--kind video|photo] [--count 6]
      лише показує кандидатів (посилання, автор, тривалість). Нічого не завантажує.
  python fetch_stock.py get --source ... --query "..." --pick 1,3 [--kind ...] --yes
      завантажує обрані кандидати в <VM_ROOT>/library/stock/ і дописує їх у library/catalog.json
      (опис = запит, джерело, автор, посилання). `--yes` лише після згоди користувача на завантаження.

Куди звертається: *.pexels.com, *.pixabay.com, *.mixkit.co (API лише з ключем, файли через `add`). Більше нікуди.
Ліцензії Pexels і Pixabay дозволяють комерційне використання без атрибуції, але з обмеженнями (наприклад, не
подавати людей зі знімків як схвалення продукту, не продавати файли як є). Перевір актуальні умови сервісу сам.
Запити англійською дають кращі результати. Для вертикального відео береться portrait.
  python fetch_stock.py --self-test    перевірка логіки без мережі
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as vm  # noqa: E402

ALLOWED = ("pexels.com", "pixabay.com", "mixkit.co")
LICENSE = {"mixkit": "Mixkit Free License (вільна, комерційна; перевір умови: mixkit.co/license)",
           "pexels": "Pexels License (вільна, комерційна; перевір умови: pexels.com/license)",
           "pixabay": "Pixabay Content License (вільна, комерційна; перевір умови: pixabay.com/service/license-summary)"}
UA = {"User-Agent": "toolkit-stock/1.0"}


def host_ok(url):
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return urllib.parse.urlparse(url).scheme == "https" and any(h == d or h.endswith("." + d) for d in ALLOWED)


def http_json(url, headers=None):
    if not host_ok(url):
        sys.exit(f"Відмова: адреса поза списком дозволених сервісів: {url[:80]}")
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"API відповіла {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
    except urllib.error.URLError as e:
        sys.exit(f"Немає зв'язку: {e.reason}")


def key(source):
    k = os.environ.get("PEXELS_API_KEY" if source == "pexels" else "PIXABAY_API_KEY")
    if not k:
        sys.exit(f"Задайте змінну середовища {'PEXELS_API_KEY' if source == 'pexels' else 'PIXABAY_API_KEY'} (безкоштовний ключ сервісу).")
    return k


def best_video(files):
    """Файл, найближчий до 1080 по ширині, але не менше 720."""
    ok = [f for f in files if f.get("width", 0) >= 720 and f.get("link")] or [f for f in files if f.get("link")]
    return min(ok, key=lambda f: abs(f.get("width", 0) - 1080)) if ok else None


def search(source, query, kind, count, fetch=http_json):
    q = urllib.parse.quote(query)
    cands = []
    if source == "pexels":
        hdr = {"Authorization": key(source)}
        if kind == "video":
            d = fetch(f"https://api.pexels.com/videos/search?query={q}&per_page={count}&orientation=portrait", hdr)
            for v in d.get("videos", []):
                f = best_video(v.get("video_files", []))
                if f:
                    cands.append({"id": v["id"], "url": f["link"], "page": v.get("url", ""), "author": (v.get("user") or {}).get("name", ""),
                                  "duration": v.get("duration", 0), "ext": ".mp4"})
        else:
            d = fetch(f"https://api.pexels.com/v1/search?query={q}&per_page={count}&orientation=portrait", hdr)
            for p in d.get("photos", []):
                cands.append({"id": p["id"], "url": p["src"].get("large2x") or p["src"]["original"], "page": p.get("url", ""),
                              "author": p.get("photographer", ""), "duration": 0, "ext": ".jpg"})
    else:
        k = key(source)
        if kind == "video":
            d = fetch(f"https://pixabay.com/api/videos/?key={k}&q={q}&per_page={max(3, count)}")
            for h in d.get("hits", [])[:count]:
                vs = h.get("videos", {})
                f = vs.get("large") or vs.get("medium") or vs.get("small")
                if f and f.get("url"):
                    cands.append({"id": h["id"], "url": f["url"], "page": h.get("pageURL", ""), "author": h.get("user", ""),
                                  "duration": h.get("duration", 0), "ext": ".mp4"})
        else:
            d = fetch(f"https://pixabay.com/api/?key={k}&q={q}&image_type=photo&orientation=vertical&per_page={max(3, count)}")
            for h in d.get("hits", [])[:count]:
                cands.append({"id": h["id"], "url": h.get("largeImageURL") or h.get("webformatURL"), "page": h.get("pageURL", ""),
                              "author": h.get("user", ""), "duration": 0, "ext": ".jpg"})
    return cands


def download(url, dest):
    if not host_ok(url):
        sys.exit(f"Відмова: адреса поза списком дозволених сервісів: {url[:80]}")
    req = urllib.request.Request(url, headers=UA)
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as f:
        if not host_ok(r.geturl()):   # редирект на інший хост: зупиняємось
            f.close()
            part.unlink(missing_ok=True)
            sys.exit(f"Відмова: редирект на недозволену адресу: {r.geturl()[:90]}")
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    part.rename(dest)


def add_to_catalog(entries):
    cat_path = vm.LIBRARY / "catalog.json"
    cat = json.loads(cat_path.read_text(encoding="utf-8")) if cat_path.exists() else {"clips": []}
    known = {c["file"] for c in cat["clips"]}
    for e in entries:
        if e["file"] not in known:
            cat["clips"].append(e)
    cat_path.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")


MAX_BYTES = 400 * 1024 * 1024
FILE_EXT = {".mp4", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".webp"}


def add_one(source, url, page, author, yes):
    """Завантажити один файл, який вказав агент (без ключів). Повертає запис каталогу."""
    if not host_ok(url):
        sys.exit(f"Відмова: адреса поза дозволеними сервісами (*.pexels.com, *.pixabay.com, *.mixkit.co, лише https): {url[:90]}")
    path = urllib.parse.urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext not in FILE_EXT:
        sys.exit(f"Відмова: очікується пряме посилання на файл {sorted(FILE_EXT)}, а не сторінка: {url[:90]}")
    if not yes:
        sys.exit("Завантаження лише з прапором --yes (після згоди користувача).")
    out = vm.LIBRARY / "stock"
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(path))[0])[:60] or "clip"
    name = f"{source}_{stem}{ext}"
    download(url, out / name)
    if (out / name).stat().st_size > MAX_BYTES:
        (out / name).unlink()
        sys.exit("Файл завеликий (понад 400 МБ): видалено.")
    return {"file": f"stock/{name}", "kind": "photo" if ext in {".jpg", ".jpeg", ".png", ".webp"} else "video", "duration": 0,
            "width": 0, "height": 0, "description": "", "tags": [], "sensitive": False, "sensitive_reason": "", "disabled": False,
            "source": f"{source}", "license": LICENSE[source], "author": author, "page": page}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["search", "get", "add"])
    ap.add_argument("--url")
    ap.add_argument("--page", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--source", choices=["pexels", "pixabay", "mixkit"], default="pexels")
    ap.add_argument("--query")
    ap.add_argument("--kind", choices=["video", "photo"], default="video")
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--pick", help="номери кандидатів через кому (з 1)")
    ap.add_argument("--yes", action="store_true", help="підтвердження користувача на завантаження")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.cmd == "add":
        if not a.url:
            sys.exit("Потрібен --url (пряме посилання на файл) і --page (сторінка кліпа).")
        add_to_catalog([add_one(a.source, a.url, a.page, a.author, a.yes)])
        print("Додано. Далі: library_catalog.py scan, потім describe для опису кадру.")
        return
    if not a.cmd or not a.query:
        sys.exit(__doc__)
    if a.source == "mixkit":
        sys.exit("Mixkit не має API: знайди кліп на сайті й додай командою add.")
    cands = search(a.source, a.query, a.kind, min(max(a.count, 1), 15))
    for i, c in enumerate(cands, 1):
        d = f", {c['duration']} с" if c["duration"] else ""
        print(f"{i}. {a.source} #{c['id']}{d}, автор: {c['author']}, сторінка: {c['page']}")
    if not cands:
        print("Нічого не знайдено: спробуй інший запит (англійською).")
    if a.cmd == "search":
        return
    if not a.yes:
        sys.exit("Завантаження лише з прапором --yes (після згоди користувача).")
    pick = [int(x) for x in (a.pick or "").split(",") if x.strip()] or [1]
    out = vm.LIBRARY / "stock"
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for n in pick:
        if not 1 <= n <= len(cands):
            sys.exit(f"Немає кандидата {n}")
        c = cands[n - 1]
        name = f"{a.source}_{c['id']}{c['ext']}"
        download(c["url"], out / name)
        entries.append({"file": f"stock/{name}", "kind": a.kind, "duration": c["duration"], "width": 0, "height": 0,
                        "description": "", "tags": [a.query], "sensitive": False, "sensitive_reason": "", "disabled": False,
                        "source": f"{a.source}:{c['id']}", "license": LICENSE[a.source], "author": c["author"], "page": c["page"]})
        print("завантажено:", out / name)
    add_to_catalog(entries)
    print("Далі: library_catalog.py scan (дізнатися розміри й зробити контактний лист), потім опиши кадри describe.")


def self_test():
    assert host_ok("https://videos.pexels.com/x.mp4") and host_ok("https://cdn.pixabay.com/a.mp4")
    assert not host_ok("http://videos.pexels.com/x") and not host_ok("https://evil.com/pexels.com") and not host_ok("https://pexels.com.evil.com/x")
    os.environ["PEXELS_API_KEY"] = "k"; os.environ["PIXABAY_API_KEY"] = "k"
    px = {"videos": [{"id": 7, "url": "https://www.pexels.com/video/7/", "duration": 9, "user": {"name": "A"},
                      "video_files": [{"width": 540, "link": "https://videos.pexels.com/a540.mp4"}, {"width": 1080, "link": "https://videos.pexels.com/a1080.mp4"},
                                      {"width": 2160, "link": "https://videos.pexels.com/a2160.mp4"}]}]}
    c = search("pexels", "cash money", "video", 3, fetch=lambda u, h=None: px)
    assert c[0]["url"].endswith("a1080.mp4") and c[0]["id"] == 7, c
    pb = {"hits": [{"id": 5, "pageURL": "https://pixabay.com/p/5", "user": "B", "duration": 4, "videos": {"large": {"url": "https://cdn.pixabay.com/v.mp4"}}}]}
    c = search("pixabay", "x", "video", 3, fetch=lambda u, h=None: pb)
    assert c[0]["ext"] == ".mp4" and c[0]["author"] == "B"
    import tempfile
    for bad in ("https://evil.com/a.mp4", "http://assets.mixkit.co/a.mp4", "https://assets.mixkit.co/videos/1/page"):
        try:
            add_one("mixkit", bad, "", "", True)
            raise AssertionError("мало відмовити: " + bad)
        except SystemExit:
            pass
    # успішний шлях add з підміною download (без мережі)
    global download
    real, calls = download, []
    download = lambda u, d: (calls.append(str(d)), d.write_bytes(b"x"))[0]
    old_lib = vm.LIBRARY
    vm.LIBRARY = Path(tempfile.mkdtemp())
    try:
        e = add_one("mixkit", "https://assets.mixkit.co/videos/preview/mixkit-test-1.mp4", "https://mixkit.co/x", "A", True)
        assert e["file"] == "stock/mixkit_mixkit-test-1.mp4" and e["kind"] == "video" and calls, e
    finally:
        download, vm.LIBRARY = real, old_lib
    print("self-test ok")


if __name__ == "__main__":
    main()
