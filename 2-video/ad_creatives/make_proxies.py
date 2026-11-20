# -*- coding: utf-8 -*-
"""Phone footage -> light proxies for editing: 1080x1920, 30 fps CFR, SAR 1, yuv420p, short GOP (15).

Usage (run from the project folder; proxies go to ./proxy):
    python make_proxies.py <folder_with_raw_videos> [--ext MOV,MP4]

Прибирає дублі кадрів (mpdecimate; вимкнути --no-dedup). Autorotates, scale-to-cover + center-crop to 1080x1920 (a horizontal source is cropped, not letterboxed).
Skips files whose proxy already exists. Needs ffmpeg (see scripts/vm_config.py).
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vm_config as vm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("src_dir")
ap.add_argument("--ext", default="MOV,MP4")
ap.add_argument("--no-dedup", action="store_true", help="не прибирати дублі кадрів (за замовчуванням прибираємо)")
a = ap.parse_args()

# Телефонні 50/60 fps із нерівними дублями кадрів після склейки в 30 fps «лагають». mpdecimate прибирає дублі, fps=30 вирівнює.
dedup = "" if a.no_dedup else "mpdecimate,"
SRC = Path(a.src_dir)
OUT = Path.cwd() / "proxy"
OUT.mkdir(exist_ok=True)
exts = {"." + e.strip().lower() for e in a.ext.split(",")}
for f in sorted(p for p in SRC.iterdir() if p.suffix.lower() in exts):
    t = OUT / (f.stem + ".mp4")
    if t.exists():
        continue
    part = OUT / (f.stem + ".part.mp4")
    # autorotate -> 1080x1920, CFR 30, SAR 1, yuv420p, short GOP for accurate cuts
    subprocess.run([vm.FFMPEG, "-y", "-v", "error", "-threads", "4", "-i", str(f), "-map", "0:v:0", "-map", "0:a:0?",
                    "-vf", f"{dedup}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-g", "15",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(part)], check=True)
    part.rename(t)
    print(f.stem, "done", flush=True)
