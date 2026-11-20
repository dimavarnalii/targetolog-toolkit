# -*- coding: utf-8 -*-
"""Каталог ВАШОЇ бібліотеки перебивок (відео й фото) з описами: за описами агент підбирає кадри під слова.

Бібліотека: <VM_ROOT>/library/<категорія>/<файл>.mp4|.mov|.jpg|.png (можна й просто в корені library/).
Каталог: <VM_ROOT>/library/catalog.json (створюється й доповнюється цим скриптом; ваші описи не перезаписуються).

Команди (з папки проєкту):
  python library_catalog.py scan            знайти нові файли, додати в каталог, зробити контактні листи нових кадрів
  python library_catalog.py check           показати файли без опису (їх агент не бачить)
  python library_catalog.py describe <file> "що в кадрі і під які фрази підходить" [--sensitive "причина"] [--tags a,b] [--disable]
                                       [--era before|after] [--lowres]   (era: для платформи yt, не змішувати «до» і «після»)

Опис має бути точним і конкретним: «жінка рахує купюри за столом, вид зверху; під фрази про гроші, дохід, оплату».
Агент дивиться контактний лист (preview/library/NN.png), пише описи сам і показує вам; чутливі кадри
(лікарня, рани, оголене тіло, чужі обличчя) позначає --sensitive: агент бачить їх із позначкою «чутливе» і ставить лише за вашим дозволом
(на платформі yt кадри з причиною «тіло» виключаються автоматично).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vm_config as vm  # noqa: E402

LIB = vm.LIBRARY
CAT = LIB / "catalog.json"
VIDEO = {".mp4", ".mov", ".m4v"}
PHOTO = {".jpg", ".jpeg", ".png", ".webp"}


def load():
    if CAT.exists():
        return json.loads(CAT.read_text(encoding="utf-8"))
    return {"clips": []}


def save(cat):
    LIB.mkdir(parents=True, exist_ok=True)
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")


def probe(path):
    out = subprocess.run([vm.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    try:
        d = json.loads(out.stdout)
        dur = d.get("format", {}).get("duration")
        return d["streams"][0]["width"], d["streams"][0]["height"], round(float(dur), 2) if dur else 0.0
    except (KeyError, IndexError, ValueError):
        return 0, 0, 0.0


def scan():
    cat = load()
    known = {c["file"] for c in cat["clips"]}
    files = sorted(p for p in LIB.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO | PHOTO
                   and not any(part.startswith("_") for part in p.relative_to(LIB).parts[:-1]))
    new = []
    for p in files:
        rel = p.relative_to(LIB).as_posix()
        if rel in known:
            continue
        w, h, dur = probe(p)
        kind = "photo" if p.suffix.lower() in PHOTO else "video"
        cat["clips"].append({"file": rel, "kind": kind, "duration": dur, "width": w, "height": h, "description": "",
                             "tags": [], "sensitive": False, "sensitive_reason": "", "disabled": False,
                             "source": "own", "license": ""})
        new.append(rel)
    save(cat)
    print(f"У каталозі {len(cat['clips'])} файлів, нових {len(new)}.")
    if new:
        sheets(new)


def sheets(rels):
    pv = Path.cwd() / "preview" / "library"
    pv.mkdir(parents=True, exist_ok=True)
    for old in pv.glob("*"):
        old.unlink()
    for n in range(0, len(rels), 25):
        chunk = rels[n:n + 25]
        for i, rel in enumerate(chunk):
            lbl = Path(rel).stem.replace("'", "").replace(":", "").replace("\\", "")
            src = LIB / rel
            ss = ["-ss", "1.0"] if src.suffix.lower() in VIDEO else []
            subprocess.run([vm.FFMPEG, "-y", "-v", "error", *ss, "-i", str(src), "-frames:v", "1", "-vf",
                            "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:0,"
                            f"drawtext={vm.drawtext_font_opt()}text='{n + i:03d} {lbl}':fontcolor=yellow:fontsize=18:x=4:y=4:box=1:boxcolor=black",
                            str(pv / f"t{i:02d}.png")], check=False)
        subprocess.run([vm.FFMPEG, "-y", "-v", "error", "-i", str(pv / "t%02d.png"), "-vf", "tile=5x5", "-frames:v", "1",
                        str(pv / f"sheet_{n // 25:02d}.png")], check=False)
        for t in pv.glob("t*.png"):
            t.unlink()
    print("Контактні листи нових файлів:", pv, "(подивись їх і опиши кадри командою describe)")
    for i, rel in enumerate(rels):
        print(f"  {i:03d}  {rel}")


def check():
    cat = load()
    miss = [c["file"] for c in cat["clips"] if not c.get("description") and not c.get("disabled")]
    print(f"Без опису: {len(miss)} з {len(cat['clips'])}")
    for f in miss:
        print("  ", f)
    return 1 if miss else 0


def describe(args):
    if len(args) < 2:
        sys.exit('Використання: describe <file> "опис" [--sensitive "причина"] [--tags a,b] [--disable]')
    file, text, rest = args[0], args[1], args[2:]
    cat = load()
    c = next((x for x in cat["clips"] if x["file"] == file), None)
    if not c:
        sys.exit(f"Немає в каталозі: {file}. Спершу scan.")
    c["description"] = text
    i = 0
    while i < len(rest):
        if rest[i] == "--sensitive":
            c["sensitive"], c["sensitive_reason"] = True, rest[i + 1]; i += 2
        elif rest[i] == "--tags":
            c["tags"] = [t.strip() for t in rest[i + 1].split(",") if t.strip()]; i += 2
        elif rest[i] == "--disable":
            c["disabled"] = True; i += 1
        elif rest[i] == "--era":
            c["era"] = rest[i + 1]; i += 2
        elif rest[i] == "--lowres":
            c["lowres"] = True; i += 1
        else:
            sys.exit(f"Невідомий параметр {rest[i]}")
    save(cat)
    print("збережено:", file)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "scan":
        scan()
    elif cmd == "check":
        sys.exit(check())
    elif cmd == "describe":
        describe(sys.argv[2:])
    else:
        sys.exit(__doc__)
