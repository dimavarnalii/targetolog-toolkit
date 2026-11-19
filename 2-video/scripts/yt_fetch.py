# -*- coding: utf-8 -*-
"""Step 1 of a shorts montage: get the source video + a timestamped transcript.

Usage:
    python yt_fetch.py <youtube-url | local video path> <project_name> [--model small] [--lang ru]

Does, in order (each step is skipped if its output already exists, so re-running is cheap):
  1. yt-dlp download (<=1440p, mp4) into <VM_ROOT>/sources/<project_name>.mp4
     (a local file is used as-is, not copied)
  2. meta.json in <VM_ROOT>/projects/<project_name>/ (title, channel, duration, url, size)
  3. audio16k.wav -> words.json (faster-whisper, word timestamps)
  4. segments.txt  — "[  12.3] sentence text" per whisper segment, for picking clip moments

Transcribing 10 min of audio took ~8 min with `small` on the author's CPU-only laptop (medium ~3x longer),
so run this in the background. Download only content you own or have rights to.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

PY = cfg.PY
YTDLP = [PY, "-m", "yt_dlp"]  # pip install yt-dlp (in the same Python as faster-whisper)
FFMPEG = cfg.FFMPEG
FFPROBE = cfg.FFPROBE
SCRIPTS = Path(__file__).resolve().parent
# YouTube may need a JS runtime for yt-dlp (Node.js). Added only if node is installed.
JS = ["--js-runtimes", "node"] if shutil.which("node") else []

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("project")
ap.add_argument("--model", default="small")
ap.add_argument("--lang", default=None)
args = ap.parse_args()

proj = cfg.PROJECTS / args.project
proj.mkdir(parents=True, exist_ok=True)
meta_path = proj / "meta.json"
meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

is_url = args.source.startswith("http")
if is_url:
    cfg.SOURCES.mkdir(parents=True, exist_ok=True)
    src = cfg.SOURCES / f"{args.project}.mp4"
    if not src.exists():
        print("1/4 Downloading...", flush=True)
        info = subprocess.run(
            [*YTDLP, *JS, "--no-playlist", "--dump-json", args.source],
            capture_output=True, text=True, encoding="utf-8", check=True).stdout
        info = json.loads(info)
        meta.update({"title": info.get("title"), "channel": info.get("channel"),
                     "url": info.get("webpage_url"), "duration": info.get("duration")})
        subprocess.run(
            [*YTDLP, *JS, "--no-playlist", *(["--ffmpeg-location", str(Path(FFMPEG).parent)] if Path(FFMPEG).is_absolute() else []),
             "-f", "bv*[height<=1440]+ba/b", "--merge-output-format", "mp4",
             "-o", str(src), args.source],
            check=True, stdout=subprocess.DEVNULL)
else:
    src = Path(args.source)
    if not src.exists():
        sys.exit(f"Not found: {src}")

probe = json.loads(subprocess.run(
    [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
     "stream=width,height,r_frame_rate,codec_name:format=duration", "-of", "json", str(src)],
    capture_output=True, text=True, check=True).stdout)
st = probe["streams"][0]
meta.update({"source_video": str(src).replace("\\", "/"),
             "width": st["width"], "height": st["height"], "fps": st["r_frame_rate"], "codec": st["codec_name"],
             "duration": float(probe["format"]["duration"])})
meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"2/4 {meta.get('title', src.name)} | {st['width']}x{st['height']} {st['codec_name']} | "
      f"{meta['duration']:.0f}s", flush=True)

wav = proj / "audio16k.wav"
if not wav.exists():
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-vn", "-ar", "16000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(wav)], check=True)

words = proj / "words.json"
if not words.exists():
    print(f"3/4 Transcribing ({args.model})...", flush=True)
    cmd = [PY, str(SCRIPTS / "transcribe_words.py"), str(wav), str(words), "--model", args.model]
    if args.lang:
        cmd += ["--lang", args.lang]
    subprocess.run(cmd, check=True)

data = json.loads(words.read_text(encoding="utf-8"))
bounds = data["segment_starts"] + [1e9]
lines = []
for a, b in zip(bounds, bounds[1:]):
    t = " ".join(w["word"] for w in data["words"] if a <= w["start"] < b)
    if t:
        lines.append(f"[{a:7.1f}] {t}")
(proj / "segments.txt").write_text("\n".join(lines), encoding="utf-8")
print(f"4/4 Done: {proj / 'segments.txt'} ({len(lines)} segments)")
