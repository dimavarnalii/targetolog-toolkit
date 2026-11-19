# -*- coding: utf-8 -*-
"""Contact sheet (5x5 tiles, labelled with file names) of the B-roll in YOUR library folder, to pick cutaways.

Usage (from the project folder):  python broll_sheet.py [library_dir]
Default library_dir = <VM_ROOT>/library. Looks at *.mp4 in the folder and one level of subfolders.
Output: preview/broll/NN.png tiles and preview/broll_sheet.png. Does not move or rename anything.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vm_config as vm  # noqa: E402

LIB = Path(sys.argv[1]) if len(sys.argv) > 1 else vm.LIBRARY
PV = Path.cwd() / "preview" / "broll"
PV.mkdir(parents=True, exist_ok=True)
for old in PV.glob("*"):
    old.unlink()
clips = sorted(list(LIB.glob("*.mp4")) + list(LIB.glob("*/*.mp4")))
if not clips:
    sys.exit(f"No .mp4 in {LIB}")
for i, f in enumerate(clips):
    lbl = f.stem.replace("'", "").replace(":", "")
    subprocess.run([vm.FFMPEG, "-y", "-v", "error", "-ss", "1.5", "-i", str(f), "-frames:v", "1", "-vf",
                    "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:0,"
                    f"drawtext={vm.drawtext_font_opt()}text='{lbl}':fontcolor=yellow:fontsize=22:x=4:y=4:box=1:boxcolor=black",
                    str(PV / f"{i:02d}.png")], check=True)
subprocess.run([vm.FFMPEG, "-y", "-v", "error", "-i", str(PV / "%02d.png"), "-vf", "tile=5x5", "-frames:v", "1",
                str(PV.parent / "broll_sheet.png")], check=True)
print(len(clips), "clips ->", PV.parent / "broll_sheet.png")
