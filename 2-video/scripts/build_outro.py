# -*- coding: utf-8 -*-
"""Builds an animated outro card (blurred freeze of the clip's last frame + a branded
image popping in with a fade+rise) and concatenates it onto the end of a rendered clip.

Usage: build_outro.py main_clip.mp4 final_output.mp4 duration image_path [fps]
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

FFMPEG = cfg.FFMPEG
FFPROBE = cfg.FFPROBE

main_clip, final_output, duration, image_path, fps = (
    sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4],
    int(sys.argv[5]) if len(sys.argv) > 5 else 25,
)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Command failed: {' '.join(cmd)}\n{r.stderr}")


probe = subprocess.run(
    [FFPROBE, "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=width,height", "-of", "csv=p=0", image_path],
    capture_output=True, text=True, check=True,
)
src_w, src_h = (int(x) for x in probe.stdout.strip().split(","))
target_w = 950
target_h = round(target_w * src_h / src_w)
rest_x = round((1080 - target_w) / 2)
rest_y = round((1920 - target_h) / 2)
rise = 40
fade_dur = 0.4

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    last_frame = tmp / "last.jpg"
    outro_clip = tmp / "outro.mp4"

    # grab the clip's last frame as the outro background plate
    run([FFMPEG, "-y", "-sseof", "-0.2", "-i", main_clip, "-frames:v", "1", str(last_frame)])

    kb = f"zoompan=z='min(1+0.05*on/({fps}*{duration}),1.05)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}"
    y_expr = f"if(lt(t\\,{fade_dur})\\,{rest_y + rise}-{rise}*t/{fade_dur}\\,{rest_y})"
    run([
        FFMPEG, "-y",
        "-loop", "1", "-i", str(last_frame),
        "-loop", "1", "-t", str(duration), "-i", image_path,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-filter_complex",
        f"[0:v]gblur=sigma=25,eq=brightness=-0.15,{kb}[bg];"
        f"[1:v]scale={target_w}:{target_h},fps={fps},fade=t=in:st=0:d={fade_dur}:alpha=1[card];"
        f"[bg][card]overlay=x={rest_x}:y='{y_expr}',setsar=1[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100",
        str(outro_clip),
    ])

    concat_filter = "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[vc][a];[vc]setsar=1[v]"
    run([
        FFMPEG, "-y", "-i", main_clip, "-i", str(outro_clip),
        "-filter_complex", concat_filter, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-movflags", "+faststart",
        final_output,
    ])

print(f"Outro appended: {final_output}")
