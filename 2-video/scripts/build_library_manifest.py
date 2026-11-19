# -*- coding: utf-8 -*-
"""Scans Перебивки_бібліотека, probes each clip, writes manifest.json.
Tags are hand-maintained below (new clips need a tags entry or fall back to []).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

LIBRARY_ROOT = cfg.LIBRARY  # <VM_ROOT>/library/<category>/<clip>.mp4
FFPROBE = cfg.FFPROBE

# Теги — ваші. Формат: "категорія/файл.mp4": ["тег1", "тег2"]. Кліп без запису отримає порожній список тегів.
TAGS = {
    # "money/counting_cash.mp4": ["гроші", "готівка", "дохід"],
    # "emotions/stress.mp4": ["стрес", "напруга"],
}


def probe(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    return {
        "width": stream["width"],
        "height": stream["height"],
        "fps": stream["r_frame_rate"],
        "duration": round(float(data["format"]["duration"]), 2),
    }


entries = []
for f in sorted(LIBRARY_ROOT.glob("*/*.mp4")):
    rel = f.relative_to(LIBRARY_ROOT).as_posix()
    info = probe(f)
    entries.append({
        "id": rel,
        "path": f.as_posix(),
        "category": f.parent.name,
        "tags": TAGS.get(rel, []),
        **info,
    })

with open(LIBRARY_ROOT / "manifest.json", "w", encoding="utf-8") as out:
    json.dump(entries, out, ensure_ascii=False, indent=2)

print(f"{len(entries)} clips indexed")
