# -*- coding: utf-8 -*-
"""Step 2 of a shorts montage: every clip of a project from ONE clips.json.

Usage:
    python shorts.py <clips.json> [clip ids...] [--stage base|render|all]

  --stage base    build only the 1080x1920 bases + preview sheet (cheap; check crops first)
  --stage render  reuse existing bases, (re)caption + render + verify
  --stage all     (default) both

Per clip, in projects/<project>/clip_<id>/:
  base.mp4      cut (one or several source segments, concatenated) + reframed to 1080x1920
  words.json    captions timing: re-transcribed from base audio with `caption_model`
                (medium = far fewer errors than small) or sliced from the full words.json
  project.json  generated config for render_project.py (defaults + clip fields)
Then render_project.py renders into done/<YYYY-MM-DD>/ with a .txt description next to
each video, verify_video.py checks it, and a preview sheet (3 frames per clip) is written to
projects/<project>/preview_sheet.jpg.

clips.json schema — see the package (references/shorts.md) for a full example:
{
  "project": "MY_PROJECT",                    # folder in <VM_ROOT>/projects (yt_fetch.py made it)
  "defaults": {
    "layout": {...},                          # used when a clip has no layout
    "caption_model": "medium", "lang": "uk",  # or "caption_model": "reuse" to slice words.json
    "render": { ...any render_project.py keys: music, image_banner, outro, intro_duration... }
  },
  "clips": [
    {"id": "1", "slug": "short_slug", "segments": [[93.1, 119.3], [242.2, 261.0]],
     "hook": "ПЕРШИЙ РЯДОК\nДРУГИЙ РЯДОК", "topic": "ТЕМА: СУТЬ",
     "keywords": ["слово1", "слово2"], "description": "текст під відео...",
     "layout": {"type": "split", "top": [0, 705, 640, 569], "bottom": [570, 230, 1160, 1031]}}
  ]
}
Layouts (rects are [x, y, w, h] in SOURCE pixels; each is scaled-to-cover + center-cropped,
so an off-ratio rect never distorts):
  split  — "top" rect -> upper 1080x960 (speaker/webcam), "bottom" rect -> lower 1080x960 (screen)
  crop   — "rect" -> full 1080x1920 (vertical reframe of a talking head)
  fit    — whole frame fitted to width over a blurred, zoomed copy of itself
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402
from verify_video import check  # noqa: E402

PY = cfg.PY
FFMPEG = cfg.FFMPEG
SCRIPTS = Path(__file__).resolve().parent
FPS = 25

RENDER_DEFAULTS = {
    "fps": FPS,
    "intro_duration": 4.5,
    "progress_bar_color": "yellow",
    # image_banner / music / outro are ON only if you set VM_BANNER / VM_MUSIC / VM_OUTRO_CARD (your own files)
    "image_banner": ({"file": cfg.BANNER.replace("\\", "/"), "width": 700, "x": 190,
                      "rest_y": 1650, "overshoot": 40, "start_t": 1.5, "rise_t": 0.8, "settle_t": 0.3,
                      "bob_amp": 15, "bob_period": 2.5} if cfg.BANNER else None),
    "music": ({"file": cfg.MUSIC.replace("\\", "/"), "volume": 0.015, "fade": 1.5} if cfg.MUSIC else None),
    "outro": ({"duration": 3.0, "image": cfg.OUTRO_CARD.replace("\\", "/")} if cfg.OUTRO_CARD else None),
    "cutaways": [],
}


def cover(rect, w, h):
    x, y, rw, rh = rect
    return (f"crop={rw}:{rh}:{x}:{y},scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={FPS}")


def layout_filter(layout, i):
    t = layout["type"]
    if t == "split":
        return (f"[{i}:v]split[s{i}a][s{i}b];[s{i}a]{cover(layout['top'], 1080, 960)}[t{i}];"
                f"[s{i}b]{cover(layout['bottom'], 1080, 960)}[b{i}];[t{i}][b{i}]vstack=2[v{i}];")
    if t == "crop":
        return f"[{i}:v]{cover(layout['rect'], 1080, 1920)}[v{i}];"
    if t == "fit":
        return (f"[{i}:v]split[s{i}a][s{i}b];"
                f"[s{i}a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:2[bg{i}];"
                f"[s{i}b]scale=1080:-2[fg{i}];[bg{i}][fg{i}]overlay=0:(H-h)/2,setsar=1,fps={FPS}[v{i}];")
    sys.exit(f"unknown layout type {t}")


def build_base(src, clip, layout, out):
    segs = clip["segments"]
    cmd = [FFMPEG, "-y", "-v", "error"]
    for s, e in segs:
        cmd += ["-ss", str(s), "-to", str(e), "-i", src]
    fc = "".join(layout_filter(layout, i) + f"[{i}:a]aresample=44100,asetpts=PTS-STARTPTS[a{i}];"
                 for i in range(len(segs)))
    if len(segs) > 1:
        fc += "".join(f"[v{i}][a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
    else:
        fc += "[v0]null[v];[a0]anull[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-r", str(FPS), "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def slice_words(full, segs):
    words, starts, off = [], [], 0.0
    for s, e in segs:
        starts.append(round(off, 3))
        starts += [round(x - s + off, 3) for x in full["segment_starts"] if s < x < e]
        words += [{"word": w["word"], "start": round(w["start"] - s + off, 3),
                   "end": round(min(w["end"], e) - s + off, 3)} for w in full["words"] if s <= w["start"] < e]
        off += e - s
    return {"words": words, "segment_starts": starts}


def caption_words(clip_dir, clip, defaults, proj):
    model = clip.get("caption_model", defaults.get("caption_model", "medium"))
    out = clip_dir / "words.json"
    if model == "reuse":
        full = json.loads((proj / "words.json").read_text(encoding="utf-8"))
        out.write_text(json.dumps(slice_words(full, clip["segments"]), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        return
    wav = clip_dir / "audio16k.wav"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(clip_dir / "base.mp4"), "-vn",
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
    cmd = [PY, str(SCRIPTS / "transcribe_words.py"), str(wav), str(out), "--model", model]
    lang = clip.get("lang", defaults.get("lang"))
    if lang:
        cmd += ["--lang", lang]
    prompt = clip.get("prompt", defaults.get("prompt"))
    if prompt:
        cmd += ["--prompt", prompt]
    subprocess.run(cmd, check=True)


def duration(path):
    return float(subprocess.run([cfg.FFPROBE, "-v", "error", "-show_entries",
                                 "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, check=True).stdout)


def deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def preview_sheet(videos, out, cols_per_clip=3):
    if not videos:
        return
    tmp = out.parent / "_preview"
    tmp.mkdir(exist_ok=True)
    n = 0
    for v in videos:
        d = duration(v)
        for t in (2.5, d / 2, max(d - 1.5, 0)):
            subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(v), "-frames:v", "1",
                            "-vf", "scale=270:480", str(tmp / f"p{n:03d}.jpg")], check=True)
            n += 1
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(tmp / "p%03d.jpg"), "-vf",
                    f"tile={cols_per_clip * min(3, len(videos))}x{-(-len(videos) // 3)}:padding=4:color=white",
                    "-frames:v", "1", str(out)], check=True)
    for f in tmp.glob("p*.jpg"):
        f.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--stage", choices=["base", "render", "all"], default="all")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    conf = json.loads(cfg_path.read_text(encoding="utf-8"))
    proj = cfg.PROJECTS / conf["project"]
    meta = json.loads((proj / "meta.json").read_text(encoding="utf-8")) if (proj / "meta.json").exists() else {}
    src = conf.get("source_video") or meta.get("source_video")
    if not src:
        sys.exit("No source_video in clips.json or meta.json")
    defaults = conf.get("defaults", {})
    clips = [c for c in conf["clips"] if not args.ids or str(c["id"]) in args.ids]

    bases, finals, failed = [], [], []
    for clip in clips:
        cid = str(clip["id"])
        clip_dir = proj / f"clip_{cid}"
        clip_dir.mkdir(exist_ok=True)
        layout = clip.get("layout") or defaults.get("layout")
        base = clip_dir / "base.mp4"

        if args.stage in ("base", "all"):
            print(f"[clip {cid}] base...", flush=True)
            build_base(src, clip, layout, base)
        bases.append(base)
        if args.stage == "base":
            continue

        print(f"[clip {cid}] captions...", flush=True)
        caption_words(clip_dir, clip, defaults, proj)

        is_split = layout["type"] == "split"
        render = deep_merge(RENDER_DEFAULTS, defaults.get("render", {}))
        render.update({
            "source_video": str(base).replace("\\", "/"),
            "output": str(cfg.DONE / f"{conf['project']}_clip{cid}_{clip.get('slug', '')}.mp4".replace("_.mp4", ".mp4")).replace("\\", "/"),
            "total_duration": round(duration(base), 2),
            "keywords": [k.lower() for k in clip.get("keywords", [])],
            "hook_text": clip.get("hook", ""),
            "topic_text": clip.get("topic", ""),
            "caption_pos": clip.get("caption_pos") or render.get("caption_pos") or ([540, 960] if is_split else [540, 1180]),
            "description": clip.get("description", ""),
        })
        render = deep_merge(render, clip.get("render", {}))
        (clip_dir / "project.json").write_text(json.dumps(render, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[clip {cid}] render...", flush=True)
        log = clip_dir / "render_run.log"
        with open(log, "w", encoding="utf-8") as f:
            r = subprocess.run([PY, str(SCRIPTS / "render_project.py"), str(clip_dir / "project.json")],
                               stdout=f, stderr=subprocess.STDOUT)
        out = next((l.split("Done: ", 1)[1].strip() for l in log.read_text(encoding="utf-8").splitlines()
                    if l.startswith("Done: ")), None)
        if r.returncode != 0 or not out:
            failed.append(cid)
            print(f"[clip {cid}] RENDER FAILED — see {log}", flush=True)
            continue
        ok, rep = check(out, render["fps"])
        print("\n".join(rep), flush=True)
        (finals if ok else failed).append(out if ok else cid)

    sheet = proj / ("bases_sheet.jpg" if args.stage == "base" else "preview_sheet.jpg")
    preview_sheet(bases if args.stage == "base" else [Path(f) for f in finals], sheet)
    print(f"\nPreview sheet: {sheet}")
    if failed:
        print(f"FAILED clips: {failed}")
        sys.exit(1)
    for f in finals:
        print(f"READY {f}")


if __name__ == "__main__":
    main()
