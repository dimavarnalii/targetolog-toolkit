# -*- coding: utf-8 -*-
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    punches = json.load(f)

AMP = 0.085      # zoom punch strength (8.5%)
HALF_W = 0.16    # half-width of the punch pulse in seconds
FPS = 25

terms = []
for t0 in punches:
    terms.append(f"{AMP}*max(0\\,1-abs(on/{FPS}-{t0})/{HALF_W})")
zoom_expr = "1" + "".join("+" + t for t in terms)

vf = (
    f"zoompan=z='{zoom_expr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS},"
    f"ass=subs_dynamic.ass"
)

with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(vf)

print(f"Filter length: {len(vf)} chars")
