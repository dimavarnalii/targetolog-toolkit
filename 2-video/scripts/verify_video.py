# -*- coding: utf-8 -*-
"""Checks a finished video for every cause of "black screen / won't play" we've hit before.

Usage: python verify_video.py <file.mp4> [...] [--fps 25] [--size 1080x1920]
(for build_creative.py output: --fps 30, size 1080x1920 or 1080x1350)
Exit code 1 if any file fails. Importable: check(path, fps, size) -> (ok, report_lines).

Checks: moov atom before mdat (faststart), constant fps, SAR 1:1, yuv420p, expected size,
H.264 + AAC, and a full decode with no errors.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

FFMPEG = cfg.FFMPEG
FFPROBE = cfg.FFPROBE


def top_level_atoms(path):
    atoms = []
    with open(path, "rb") as f:
        while True:
            head = f.read(8)
            if len(head) < 8:
                break
            size = int.from_bytes(head[:4], "big")
            kind = head[4:8].decode("latin-1")
            if size == 1:
                size = int.from_bytes(f.read(8), "big")
                f.seek(size - 16, 1)
            elif size == 0:
                atoms.append(kind)
                break
            else:
                f.seek(size - 8, 1)
            atoms.append(kind)
    return atoms


def check(path, fps=25, size="1080x1920"):
    rep, ok = [], True

    def bad(msg):
        nonlocal ok
        ok = False
        rep.append("  FAIL " + msg)

    atoms = top_level_atoms(path)
    if "moov" not in atoms or "mdat" not in atoms or atoms.index("moov") > atoms.index("mdat"):
        bad(f"moov after mdat / missing (atoms={atoms}) -> remux with -movflags +faststart")
    pr = json.loads(subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_aspect_ratio,pix_fmt:format=duration",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout)
    v = next((s for s in pr["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in pr["streams"] if s["codec_type"] == "audio"), None)
    dur = float(pr["format"]["duration"])
    if not v:
        bad("no video stream")
    else:
        if f"{v['width']}x{v['height']}" != size:
            bad(f"size {v['width']}x{v['height']} != {size}")
        if v.get("sample_aspect_ratio", "1:1") not in ("1:1", "0:1", "N/A"):
            bad(f"SAR {v['sample_aspect_ratio']} -> add setsar=1")
        if v.get("pix_fmt") != "yuv420p":
            bad(f"pix_fmt {v.get('pix_fmt')} -> -pix_fmt yuv420p")
        if v["codec_name"] != "h264":
            bad(f"video codec {v['codec_name']}")
        if v["r_frame_rate"] != f"{fps}/1" or v["avg_frame_rate"] != f"{fps}/1":
            bad(f"fps r={v['r_frame_rate']} avg={v['avg_frame_rate']} (want CFR {fps}) -> -r {fps} -fps_mode cfr")
    if not a:
        bad("no audio stream")
    elif a["codec_name"] != "aac":
        bad(f"audio codec {a['codec_name']}")
    dec = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True, text=True)
    if dec.returncode != 0 or dec.stderr.strip():
        bad("decode errors: " + dec.stderr.strip()[:300])
    rep.insert(0, f"{'OK  ' if ok else 'FAIL'} {path} | {dur:.2f}s"
               + (f" | {v['width']}x{v['height']} {v['r_frame_rate']}fps" if v else ""))
    return ok, rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--size", default="1080x1920")
    args = ap.parse_args()
    all_ok = True
    for p in args.files:
        ok, rep = check(p, args.fps, args.size)
        all_ok &= ok
        print("\n".join(rep))
    sys.exit(0 if all_ok else 1)
