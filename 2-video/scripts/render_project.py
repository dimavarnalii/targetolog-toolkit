# -*- coding: utf-8 -*-
"""One-command montage renderer, driven entirely by a project.json config.

Prerequisite: words.json must already exist in the project folder (run
transcribe_words.py once per source video beforehand — that step is slow
and only needs doing once, so it stays separate from this script).

Usage:
    python render_project.py <project_dir>\\project.json

project.json schema:
{
  "source_video": "/path/to/file.mp4",
  "output": "<VM_ROOT>/done/name_vN.mp4",   (a file directly in <VM_ROOT>/done goes into a dated subfolder)
  "total_duration": 53.52,
  "fps": 25,
  "keywords": ["слово1", "слово2", ...],
  "hook_text": "ПЕРШИЙ РЯДОК\\nДРУГИЙ РЯДОК",
  "progress_bar_color": "yellow",
  "description": "текст опису під відео (українською, з CTA) → пишеться в .txt поруч з відео",
  "music": {"file": "/path/to/your_track.mp3", "volume": 0.03, "fade": 1.5},   (optional)
  "whoosh": {"file": "/path/to/your_whoosh.mp3", "volume": 0.35},          (optional)
  "cutaways": [
    {"start": 1.0, "end": 2.3, "format": "full", "file": "/path/to/broll.mp4"},
    ...
  ]
}
"""
import json
import subprocess
from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

PYTHON = cfg.PY
FFMPEG = cfg.FFMPEG
FFPROBE = cfg.FFPROBE
SCRIPTS = Path(__file__).resolve().parent


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kw)


def main(config_path):
    config_path = Path(config_path)
    project_dir = config_path.parent
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # finished videos go into done/<YYYY-MM-DD>/ so they're easy to find by montage date
    out_path = Path(config["output"])
    if out_path.parent.resolve() == cfg.DONE.resolve():
        out_path = out_path.parent / date.today().isoformat() / out_path.name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    config["output"] = str(out_path)

    words_json = project_dir / "words.json"
    if not words_json.exists():
        sys.exit(f"Missing {words_json} — run transcribe_words.py first.")

    subs_ass = project_dir / "subs_dynamic.ass"
    punches_json = project_dir / "punches.json"
    filter_complex_txt = project_dir / "filter_complex.txt"

    print("1/4 Building subtitles...")
    run([
        PYTHON, str(SCRIPTS / "build_dynamic_ass.py"),
        str(words_json), str(config_path), str(subs_ass), str(punches_json),
    ], cwd=project_dir)

    print("2/4 Building filter graph...")
    run([
        PYTHON, str(SCRIPTS / "build_overlay_filter.py"),
        str(config_path), str(punches_json), str(filter_complex_txt),
    ], cwd=project_dir)

    print("3/4 Rendering...")
    filter_complex = filter_complex_txt.read_text(encoding="utf-8").replace("\n", "")

    ffmpeg_cmd = [FFMPEG, "-y", "-i", config["source_video"]]
    for c in config["cutaways"]:
        ffmpeg_cmd += ["-i", c["file"]]
    image_banner = config.get("image_banner")
    if image_banner:
        # -t caps the looped (infinite) image stream so overlay's default
        # eof_action=repeat can't make the whole render run forever
        ffmpeg_cmd += ["-loop", "1", "-t", str(config["total_duration"]), "-i", image_banner["file"]]
    music = config.get("music")
    if music:
        ffmpeg_cmd += ["-i", music["file"]]
    whoosh = config.get("whoosh")
    if whoosh:
        ffmpeg_cmd += ["-i", whoosh["file"]] * len(config["cutaways"])

    fps = config.get("fps", 25)
    outro = config.get("outro")
    main_output = str(project_dir / "_base_render.mp4") if outro else config["output"]
    ffmpeg_cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-r", str(fps), "-fps_mode", "cfr",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100",
        "-movflags", "+faststart",
        main_output,
    ]
    log_path = project_dir / "render.log"
    with open(log_path, "w", encoding="utf-8") as log:
        result = subprocess.run(ffmpeg_cmd, cwd=project_dir, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        sys.exit(f"ffmpeg failed (exit {result.returncode}) — see {log_path}")

    if outro:
        print("4/5 Appending outro...")
        run([
            PYTHON, str(SCRIPTS / "build_outro.py"),
            main_output, config["output"],
            str(outro.get("duration", 3.0)), outro["image"], str(fps),
        ], cwd=project_dir)
        total_expected = config["total_duration"] + outro.get("duration", 3.0)
        step = "5/5"
    else:
        total_expected = config["total_duration"]
        step = "4/4"

    print(f"{step} Verifying output...")
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames,r_frame_rate,width,height",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1", config["output"]],
        capture_output=True, text=True, check=True,
    )
    print(probe.stdout)
    expected_frames = round(total_expected * fps)
    if f"nb_frames={expected_frames}" not in probe.stdout:
        print(f"NOTE: expected ~{expected_frames} frames (total_duration + outro) — minor drift from concat re-encode is normal, check it's close.")
    description = config.get("description")
    if description:
        out_path.with_suffix(".txt").write_text(description.strip() + "\n", encoding="utf-8")
        print(f"Description: {out_path.with_suffix('.txt')}")
    print(f"Done: {config['output']}")


if __name__ == "__main__":
    main(sys.argv[1])
