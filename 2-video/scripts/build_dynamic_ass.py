# -*- coding: utf-8 -*-
"""Builds dynamic 2-word captions (+ optional hook/topic/banner) from word timestamps.
Usage: build_dynamic_ass.py words.json project.json output.ass punches.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
with open(sys.argv[2], "r", encoding="utf-8") as f:
    config = json.load(f)

words = data["words"]
seg_starts = set(round(s, 2) for s in data["segment_starts"])


def is_seg_start(w, tol=0.05):
    return any(abs(w["start"] - s) < tol for s in data["segment_starts"])


groups = []
current = []
for w in words:
    if current and is_seg_start(w):
        groups.append(current)
        current = []
    current.append(w)
    if len(current) == 2:
        groups.append(current)
        current = []
if current:
    groups.append(current)

DEFAULT_KEYWORD_STEMS = []  # keywords come from project.json ("keywords": ["основа слова", ...])
KEYWORD_STEMS = config.get("keywords") or DEFAULT_KEYWORD_STEMS
HILITE = "{\\c&H0000FFFF&}"
RESET = "{\\c&H00FFFFFF&}"


def is_keyword(word):
    clean = word.strip(".,!?:;-").lower()
    return any(clean.startswith(stem) for stem in KEYWORD_STEMS)


def fmt_ts(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int((t - int(t)) * 100)
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"


def to_ass_text(s):
    # handles both a literal "\n" (CLI-passed text) and a real newline (already
    # decoded by json.load) ending up as the ASS line-break marker "\N"
    return s.replace("\\n", "\\N").replace("\n", "\\N")


HOOK_TEXT = to_ass_text(config.get("hook_text", ""))
TOPIC_TEXT = to_ass_text(config.get("topic_text", ""))
BANNER_TEXT = to_ass_text(config.get("banner_text", ""))
CAPTION_X, CAPTION_Y = config.get("caption_pos", [540, 1180])
TOTAL_DUR = config["total_duration"]
INTRO_DUR = config.get("intro_duration", 3.0)

ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT},88,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,7,0,5,60,60,0,1
Style: Hook,{FONT},62,&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,8,80,80,160,1
Style: Topic,{FONT},40,&H0000FFFF,&H000000FF,&H00000000,&H40000000,-1,0,0,0,100,100,0,0,3,0,0,8,60,60,60,1
Style: Banner,{FONT},40,&H00FFFFFF,&H000000FF,&H00000000,&H40000000,-1,0,0,0,100,100,0,0,3,0,0,2,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

lines = [ass_header.replace("{FONT}", cfg.ASS_FONT)]

if HOOK_TEXT:
    lines.append(f"Dialogue: 0,0:00:00.00,{fmt_ts(INTRO_DUR)},Hook,,0,0,0,,{HOOK_TEXT}\n")
if TOPIC_TEXT:
    lines.append(f"Dialogue: 0,0:00:00.00,{fmt_ts(INTRO_DUR)},Topic,,0,0,0,,{TOPIC_TEXT}\n")
if BANNER_TEXT:
    # slide up from off-screen bottom to a resting position just above the frame edge, then hold
    move = "{\\move(540,2050,540,1870,300,800)}"
    lines.append(f"Dialogue: 0,0:00:01.50,{fmt_ts(TOTAL_DUR)},Banner,,0,0,0,,{move}{BANNER_TEXT}\n")

for i, g in enumerate(groups):
    start = g[0]["start"]
    end = g[-1]["end"]
    if i + 1 < len(groups):
        next_start = groups[i + 1][0]["start"]
        end = max(end, next_start - 0.02)
    parts = []
    for w in g:
        wd = w["word"].upper()
        if len(wd) > 1 and wd[0] == "-":
            wd = wd[1:]
        parts.append(f"{HILITE}{wd}{RESET}" if is_keyword(w["word"]) else wd)
    text = " ".join(parts)
    lines.append(
        f"Dialogue: 0,{fmt_ts(start)},{fmt_ts(end)},Caption,,0,0,0,,"
        f"{{\\pos({CAPTION_X},{CAPTION_Y})}}{text}\n"
    )

with open(sys.argv[3], "w", encoding="utf-8") as f:
    f.writelines(lines)

print(f"Groups: {len(groups)}")

punches = sorted(s for s in data["segment_starts"] if s > 0.1)
with open(sys.argv[4], "w", encoding="utf-8") as f:
    json.dump(punches, f)
print(f"Punches: {punches}")
