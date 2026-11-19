# -*- coding: utf-8 -*-
"""Contact sheet of source frames with a coordinate grid — for choosing crop rectangles
(where the webcam/face is, where the chart/screen is) without guessing.

Usage: python scan_sheet.py <video> <out.jpg> <t1> <t2> ... [--cols 3] [--grid 100]

Each tile = one frame at time t, labelled with t; red grid lines every --grid SOURCE pixels
(so on a 2224x1440 source with --grid 100, the 5th line from the left is x=500).
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

FFMPEG = cfg.FFMPEG

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("out")
ap.add_argument("times", nargs="+", type=float)
ap.add_argument("--cols", type=int, default=3)
ap.add_argument("--grid", type=int, default=100)
ap.add_argument("--tile_w", type=int, default=640)
args = ap.parse_args()

tmp = Path(tempfile.mkdtemp())
for i, t in enumerate(args.times):
    vf = (f"drawgrid=w={args.grid}:h={args.grid}:t=2:c=red@0.5,"
          f"scale={args.tile_w}:-2,"
          f"drawtext={cfg.drawtext_font_opt()}text='{t:g}s':x=w-tw-10:y=h-th-10:fontsize=28:fontcolor=yellow:box=1:boxcolor=black@0.7")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(t), "-i", args.video, "-frames:v", "1",
                    "-vf", vf, str(tmp / f"f{i:03d}.jpg")], check=True)
n = len(args.times)
rows = -(-n // args.cols)
subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(tmp / "f%03d.jpg"),
                "-vf", f"tile={args.cols}x{rows}:padding=4:color=white", "-frames:v", "1", args.out], check=True)
print(f"{args.out}: {n} frames, grid every {args.grid}px of source")
