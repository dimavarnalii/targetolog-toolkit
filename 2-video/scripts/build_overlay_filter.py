# -*- coding: utf-8 -*-
"""Generates filter_complex.txt from a project config.
Usage: build_overlay_filter.py project.json punches.json filter_complex.txt
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

with open(sys.argv[1], "r", encoding="utf-8") as f:
    config = json.load(f)

with open(sys.argv[2], "r", encoding="utf-8") as f:
    punches = json.load(f)

# cutaways: list of {start, end, format, file} — format is "full" (covers whole frame),
# "split" (speaker top half / cutaway bottom half), or "circle" (cutaway full-screen
# background + speaker in a circular bubble on top). Cutaway input index = position (1-based).
windows = [(c["start"], c["end"], c["format"]) for c in config["cutaways"]]

AMP = 0.085
HALF_W = 0.16
FPS = config.get("fps", 25)
zterms = [f"{AMP}*max(0\\,1-abs(on/{FPS}-{t0})/{HALF_W})" for t0 in punches]
zoom_expr = "1" + "".join("+" + t for t in zterms)

CIRCLE_D = 480
CIRCLE_X = 1080 - CIRCLE_D - 40
CIRCLE_Y = 80
TOTAL_DUR = config["total_duration"]
KB_AMOUNT = 0.08  # Ken Burns: slow zoom-in on each cutaway, 1.0 -> 1.0+KB_AMOUNT
BAR_COLOR = config.get("progress_bar_color", "yellow")


def kenburns(w, h, dur):
    z = f"min(1+{KB_AMOUNT}*on/({FPS}*{dur})\\,{1 + KB_AMOUNT})"
    return f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}"


n_split = sum(1 for w in windows if w[2] == "split")
n_circle = sum(1 for w in windows if w[2] == "circle")
n_copies = 1 + n_split + n_circle
split_labels = [f"v0n_s{i}" for i in range(n_split)]
circle_labels = [f"v0n_c{i}" for i in range(n_circle)]
all_labels = ["v0n_main"] + split_labels + circle_labels

lines = []
lines.append(f"[0:v]fps={FPS},split={n_copies}" + "".join(f"[{l}]" for l in all_labels) + ";")

prev = "v0n_main"
split_i = 0
circle_i = 0
for i, (start, end, fmt) in enumerate(windows, start=1):
    # cap each cutaway's own duration so a long source clip can never push the
    # composited stream's length past the main video (overlay/vstack default to
    # MAX(input durations) via eof_action=repeat, not the main video's length)
    cut_dur = round(end - start + 0.5, 2)

    if fmt == "full":
        lines.append(
            f"[{i}:v]fps={FPS},trim=duration={cut_dur},scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,{kenburns(1080, 1920, cut_dur)},setpts=PTS+{start}/TB[c{i}];"
        )
        out_label = f"ov{i}"
        lines.append(f"[{prev}][c{i}]overlay=enable='between(t,{start},{end})'[{out_label}];")
        prev = out_label

    elif fmt == "split":
        sp_label = split_labels[split_i]
        split_i += 1
        lines.append(
            f"[{sp_label}]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[sptop{i}];"
        )
        lines.append(
            f"[{i}:v]fps={FPS},trim=duration={cut_dur},scale=1080:960:force_original_aspect_ratio=increase,"
            f"crop=1080:960,{kenburns(1080, 960, cut_dur)},setpts=PTS+{start}/TB[cbtm{i}];"
        )
        lines.append(f"[sptop{i}][cbtm{i}]vstack=2[splitcomp{i}];")
        out_label = f"ov{i}"
        lines.append(f"[{prev}][splitcomp{i}]overlay=enable='between(t,{start},{end})'[{out_label}];")
        prev = out_label

    elif fmt == "circle":
        ci_label = circle_labels[circle_i]
        circle_i += 1
        lines.append(
            f"[{i}:v]fps={FPS},trim=duration={cut_dur},scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,{kenburns(1080, 1920, cut_dur)},setpts=PTS+{start}/TB[bg{i}];"
        )
        lines.append(
            f"[{ci_label}]crop=1080:1080:0:300,scale={CIRCLE_D}:{CIRCLE_D},format=yuva420p,"
            f"geq=lum='p(X\\,Y)':cb='p(X\\,Y)':cr='p(X\\,Y)':"
            f"a='if(lte(pow(X-W/2\\,2)+pow(Y-H/2\\,2)\\,pow(min(W\\,H)/2\\,2))\\,255\\,0)'[circ{i}];"
        )
        lines.append(f"[bg{i}][circ{i}]overlay=x={CIRCLE_X}:y={CIRCLE_Y}[circlecomp{i}];")
        out_label = f"ov{i}"
        lines.append(f"[{prev}][circlecomp{i}]overlay=enable='between(t,{start},{end})'[{out_label}];")
        prev = out_label

lines.append(
    f"[{prev}]zoompan=z='{zoom_expr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS},"
    f"setsar=1,{cfg.ass_filter('subs_dynamic.ass')}[vsubs];"
)
# progress bar: drawbox's w= is only evaluated once at init in this ffmpeg build (no
# 'eval' option), so grow it instead via a geq alpha mask (same trick as the circle
# bubble), which IS re-evaluated every frame using the T (time) variable.
lines.append(
    f"color=c={BAR_COLOR}:s=1080x10:d={TOTAL_DUR}:r={FPS},format=yuva420p,"
    f"geq=lum='p(X\\,Y)':cb='p(X\\,Y)':cr='p(X\\,Y)':a='if(lt(X\\,W*T/{TOTAL_DUR})\\,255\\,0)'[bar];"
)
lines.append("[vsubs][bar]overlay=x=0:y=0[vbar];")

# image banner (e.g. a branded CTA graphic): input index = len(windows) + 1, right after
# the cutaways. Slides in from below-left with a rise-then-settle bounce, then holds.
image_banner = config.get("image_banner")
next_idx = len(windows) + 1
if image_banner:
    BANNER_IMG_IDX = next_idx
    next_idx += 1
    bw = image_banner.get("width", 900)
    bx = image_banner.get("x", 40)
    rest_y = image_banner.get("rest_y", 1550)
    overshoot = image_banner.get("overshoot", 40)
    start_t = image_banner.get("start_t", 1.5)
    rise_t = image_banner.get("rise_t", 0.8)
    settle_t = image_banner.get("settle_t", 0.3)
    bob_amp = image_banner.get("bob_amp", 15)
    bob_period = image_banner.get("bob_period", 2.5)
    hidden_y = 1920 + 50
    peak_y = rest_y - overshoot
    t1 = start_t
    t2 = start_t + rise_t
    t3 = t2 + settle_t
    # after settling, keep a slow idle bob so the banner doesn't look frozen
    idle = f"{rest_y}+{bob_amp}*sin(2*PI*(t-{t3})/{bob_period})"
    y_expr = (
        f"if(lt(t\\,{t1})\\,{hidden_y}\\,"
        f"if(lt(t\\,{t2})\\,{hidden_y}+({peak_y}-{hidden_y})*(t-{t1})/{rise_t}\\,"
        f"if(lt(t\\,{t3})\\,{peak_y}+({rest_y}-{peak_y})*(t-{t2})/{settle_t}\\,{idle})))"
    )
    lines.append(
        f"[{BANNER_IMG_IDX}:v]scale={bw}:-1,fps={FPS}[bannerimg];"
    )
    lines.append(f"[vbar][bannerimg]overlay=x={bx}:y='{y_expr}',setsar=1[vout];")
else:
    lines.append("[vbar]setsar=1[vout];")

# background music
music = config.get("music")
MUSIC_IDX = next_idx
if music:
    MUSIC_VOLUME = music.get("volume", 0.03)
    FADE_DUR = music.get("fade", 1.5)
    lines.append(
        f"[{MUSIC_IDX}:a]atrim=duration={TOTAL_DUR},asetpts=PTS-STARTPTS,volume={MUSIC_VOLUME},"
        f"afade=t=in:st=0:d={FADE_DUR},afade=t=out:st={TOTAL_DUR - FADE_DUR}:d={FADE_DUR}[music];"
    )

# sound design: a whoosh on every cutaway's entry. Each SFX file is fed in as one -i
# input per occurrence (reusing the same source file), starting right after the music input.
whoosh = config.get("whoosh")
sfx_labels = []
if whoosh:
    WHOOSH_BASE_IDX = MUSIC_IDX + (1 if music else 0)
    WHOOSH_VOLUME = whoosh.get("volume", 0.35)
    for i, (start, end, fmt) in enumerate(windows):
        idx = WHOOSH_BASE_IDX + i
        ms = round(start * 1000)
        label = f"whoosh{i}"
        lines.append(f"[{idx}:a]adelay=delays={ms}:all=1,volume={WHOOSH_VOLUME}[{label}];")
        sfx_labels.append(label)

amix_parts = ["[0:a]"] + (["[music]"] if music else []) + [f"[{l}]" for l in sfx_labels]
n_amix = len(amix_parts)
if n_amix > 1:
    lines.append(f"{''.join(amix_parts)}amix=inputs={n_amix}:duration=first:normalize=0[aout]")
else:
    lines.append("[0:a]acopy[aout]")

with open(sys.argv[3], "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Filter complex written, {len(lines)} lines, {len(windows)} cutaways "
      f"({n_split} split, {n_circle} circle, {len(windows)-n_split-n_circle} full)")
