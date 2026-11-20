# -*- coding: utf-8 -*-
"""Підбір перебивок за змістом: бриф для агента і перевірка плану.

З папки проєкту:
  python plan_broll.py brief creatives.json <name>   -> work/<name>_broll_brief.md
      фрази з часом ДЖЕРЕЛА, місця склейок (їх треба закрити перебивкою) і кадри каталогу з описами.
      Агент читає бриф, обирає кадри ЗА ЗМІСТОМ слів і вписує `cutaways` у creatives.json.
  python plan_broll.py check creatives.json <name>   -> перевірка вписаного плану (код 1, якщо є помилки)
      файли існують і достатньо довгі; перебивки не перекриваються; немає 1-кадрових «спалахів» спікера між ними;
      склейки закриті; показує частку часу під перебивками.

Правила підбору (див. references/editing_rules.md §3): сцена дослівно збігається зі словом, що звучить; на всю фразу
(довгу фразу закривай кількома схожими, але різними кадрами); обов'язково закривай склейки; не закривай прямі звернення
до глядача й загальні міркування; чутливі/вимкнені кадри не брати; той самий кадр двічі не ставити.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_creative as bc  # noqa: E402
import vm_config as vm  # noqa: E402

PROJ = Path.cwd()


def load(cfg_path, name):
    allcfg = json.loads((PROJ / cfg_path).read_text(encoding="utf-8"))
    cfg = next((c for c in allcfg["creatives"] if c["name"] == name), None)
    if not cfg:
        sys.exit(f"Немає креативу {name}: {[c['name'] for c in allcfg['creatives']]}")
    src_dur = bc.probe_dur(PROJ / cfg["source"])
    words = json.loads((PROJ / cfg["words"]).read_text(encoding="utf-8"))["words"]
    ws, segs = bc.build_segments(words, cfg.get("exclude", []), src_dur)
    ws = bc.fix_words(ws, cfg.get("fixes", {}), cfg.get("fix_at", []))
    return cfg, ws, segs


def brief(cfg_path, name):
    cfg, ws, segs = load(cfg_path, name)
    cat_path = vm.LIBRARY / "catalog.json"
    clips = json.loads(cat_path.read_text(encoding="utf-8"))["clips"] if cat_path.exists() else []
    usable = [c for c in clips if c.get("description") and not c.get("sensitive") and not c.get("disabled")]
    lines = [f"# Бриф перебивок: {name}", "",
             "Час у секундах ДЖЕРЕЛА (так само, як `at` у creatives.json). Обери кадри за змістом слів. Правила — у plan_broll.py (шапка).", "",
             "## Склейки (закрий перебивкою)", ""]
    joins = [round(s, 2) for s, _ in segs[1:]]
    lines.append(", ".join(f"{j}" for j in joins) or "(немає)")
    lines += ["", "## Текст за фразами", ""]
    cur, start = [], None
    for w in ws:
        if start is None:
            start = w["start"]
        cur.append(w["word"])
        if w["word"].rstrip().endswith((".", "?", "!")) or len(cur) >= 14:
            lines.append(f"[{start:6.2f}] {' '.join(cur)}")
            cur, start = [], None
    if cur:
        lines.append(f"[{start:6.2f}] {' '.join(cur)}")
    lines += ["", f"## Кадри каталогу ({len(usable)} з описами; без опису, чутливі й вимкнені не показано)", ""]
    for c in usable:
        d = f"{c['duration']}с" if c["kind"] == "video" else "фото"
        lines.append(f"- `lib/{Path(c['file']).with_suffix('').as_posix()}` ({c['kind']}, {d}): {c['description']}")
    if not usable:
        lines.append("(каталог порожній: `library_catalog.py scan`, потім опиши кадри)")
    out = PROJ / "work" / f"{name}_broll_brief.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"бриф: {out} (фраз: {sum(1 for l in lines if l.startswith('['))}, кадрів: {len(usable)}, склейок: {len(joins)})")


def check(cfg_path, name):
    cfg, ws, segs = load(cfg_path, name)
    speed = bc.pick_speed(cfg, len(ws), sum(e - s for s, e in segs))
    total = sum(e - s for s, e in segs) / speed
    errs, warns, wins = [], [], []
    seen = set()
    for k, c in enumerate(cfg.get("cutaways", [])):
        p = bc.resolve_media(c["file"])
        if not p:
            errs.append(f"#{k} немає файлу: {c['file']}"); continue
        dur = c.get("dur", 1.6)
        if not bc.is_image(p) and c.get("ss", 0) + dur > bc.probe_dur(p):
            errs.append(f"#{k} {c['file']} закороткий для ss={c.get('ss', 0)} dur={dur}")
        if c["file"] in seen:
            warns.append(f"#{k} цей кадр уже стоїть раніше: {c['file']}")
        seen.add(c["file"])
        a = bc.src_to_out(c["at"], segs) / speed
        wins.append((a, min(a + dur, total), k))
    wins.sort()
    for (a0, b0, k0), (a1, b1, k1) in zip(wins, wins[1:]):
        if a1 < b0 - 0.01:
            errs.append(f"#{k0} і #{k1} перекриваються ({a1:.2f}с < {b0:.2f}с)")
        elif 0 < a1 - b0 < 1.0:
            warns.append(f"між #{k0} і #{k1} щілина {a1 - b0:.2f}с: спікер «мигне». Став встик або на ≥1 с")
    open_joins = []
    acc = 0.0
    for s, e in segs[:-1]:
        acc += (e - s) / speed
        if not any(a - 0.15 <= acc <= b + 0.15 for a, b, _ in wins):
            open_joins.append(round(acc, 2))
    if open_joins:
        warns.append(f"не закриті склейки (час ролика, с): {open_joins}")
    covered = sum(b - a for a, b, _ in wins)
    print(f"перебивок: {len(wins)}, під ними {covered:.1f} із {total:.1f} с ({covered / total * 100:.0f}%)" if total else "порожньо")
    for w in warns:
        print("УВАГА:", w)
    for e in errs:
        print("ПОМИЛКА:", e)
    if not errs:
        print("план перебивок: помилок немає")
    return 1 if errs else 0


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] not in ("brief", "check"):
        sys.exit(__doc__)
    if sys.argv[1] == "brief":
        brief(sys.argv[2], sys.argv[3])
    else:
        sys.exit(check(sys.argv[2], sys.argv[3]))
