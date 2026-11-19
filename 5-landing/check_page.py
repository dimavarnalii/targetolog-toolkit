#!/usr/bin/env python3
"""Перевірка готової сторінки перед запуском реклами.  python check_page.py out/
Не інтернет-запити: лише аналіз файлів. Видає КРИТИЧНО / УВАГА / ОК."""
import os, re, sys, json
from html.parser import HTMLParser

d = sys.argv[1] if len(sys.argv) > 1 else "out"
res = []
def add(level, text): res.append((level, text))

class P(HTMLParser):
    def __init__(s):
        super().__init__(); s.h1 = 0; s.imgs = 0; s.noalt = 0; s.vp = False; s.desc = False
        s.tel = False; s.form = False; s.ext = []
    def handle_starttag(s, t, a):
        a = dict(a)
        if t == "h1": s.h1 += 1
        if t == "img":
            s.imgs += 1
            if not a.get("alt"): s.noalt += 1
        if t == "meta" and a.get("name") == "viewport": s.vp = True
        if t == "meta" and a.get("name") == "description" and a.get("content"): s.desc = True
        if t == "a" and str(a.get("href", "")).startswith("tel:"): s.tel = True
        if t == "form": s.form = True
        for k in ("src", "href"):
            v = a.get(k, "")
            if v.startswith("http") and t in ("script", "link", "img"): s.ext.append(v)

def read(f):
    return open(os.path.join(d, f), encoding="utf8").read()

try:
    idx, th = read("index.html"), read("thanks.html")
except FileNotFoundError:
    sys.exit("У папці немає index.html / thanks.html")

p = P(); p.feed(idx)
kb = len(idx.encode()) / 1024
imgkb = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(os.path.join(d, "img")) for f in fs) / 1024 if os.path.isdir(os.path.join(d, "img")) else 0
(add("УВАГА", f"Вага картинок {imgkb:.0f} КБ: стисніть до 150-250 КБ кожну (WebP/JPG)") if imgkb > 800 else add("ОК", f"Вага HTML {kb:.0f} КБ, картинок {imgkb:.0f} КБ"))

if "ДЕМО-РЕЖИМ" in idx: add("КРИТИЧНО", "Не задано tracking.endpoint: заявки нікуди не йдуть (демо-режим)")
else: add("ОК", "endpoint заданий")
m = re.search(r"fbq\('init','(\d+)'\)", idx)
if not m: add("КРИТИЧНО", "Немає Meta Pixel (tracking.pixel_id): реклама не отримає подій")
else: add("ОК", f"Pixel {m.group(1)} підключений; Lead спрацьовує на thanks.html")
if "fbq('track','Lead'" not in th: add("КРИТИЧНО", "На thanks.html немає події Lead")
if p.h1 != 1 and 'id="qbox"' not in idx: add("УВАГА", f"H1 має бути один, зараз {p.h1}")
if p.noalt: add("УВАГА", f"{p.noalt} із {p.imgs} зображень без alt")
if not p.vp: add("КРИТИЧНО", "Немає meta viewport (сторінка не адаптується під телефон)")
if not p.desc: add("УВАГА", "Немає meta description")
if not p.tel and "tel:" not in idx: add("УВАГА", "Немає клікабельного телефону (tel:)")
if not p.form and 'id="qbox"' not in idx: add("КРИТИЧНО", "Немає форми")
if p.ext: add("УВАГА", "Зовнішні ресурси гальмують сторінку: " + ", ".join(sorted(set(p.ext))[:4]))
vis = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", idx, flags=re.S)
if re.search(r"(TODO|\bXXX\b|lorem|\[\.\.\.\])", vis, re.I) and "0XX" not in vis.replace("0XX XXX XX XX", ""): add("КРИТИЧНО", "У сторінці лишились заглушки")
if "вигадані" in idx.lower() or "демо" in idx.lower(): add("УВАГА", "Є позначки «демо/вигадані дані»: приберіть перед запуском")
if "noindex" in idx: add("ОК", "Сторінка закрита від індексації (рекламна сторінка)")

# Політика реклами та довіра: лише підказки для перевірки людиною, не вердикт
txt = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", idx, flags=re.S)
flags = [
    (r"гарантуєм\w*|гарантован\w*|100\s?%", "гарантії результату"),
    (r"до і після|до та після", "«до/після»"),
    (r"останн\w+ \d+ (місц|шт)|залишилось \d+", "штучний дефіцит (має бути правдою)"),
    (r"відгук|клієнт\w* каж", "відгуки (мають бути справжніми, з дозволу)"),
    (r"\bви (хворі|в боргах|самотні|товсті)\b", "персональні ознаки в тексті: порушення правил Meta"),
]
for rx, name in flags:
    if re.search(rx, txt, re.I): add("УВАГА", f"Перевірте очима: {name}")
if not re.search(r"персональн", idx, re.I): add("УВАГА", "Немає згоди на обробку персональних даних біля форми")

order = {"КРИТИЧНО": 0, "УВАГА": 1, "ОК": 2}
for lv, t in sorted(res, key=lambda x: order[x[0]]): print(f"[{lv}] {t}")
sys.exit(1 if any(l == "КРИТИЧНО" for l, _ in res) else 0)
