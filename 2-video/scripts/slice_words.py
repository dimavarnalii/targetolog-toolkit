# -*- coding: utf-8 -*-
"""Slices a full words.json down to a clip's local time range, rebasing timestamps to 0.
Usage: slice_words.py full_words.json start end output_words.json
"""
import json
import sys

full_path, start, end, out_path = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]

with open(full_path, "r", encoding="utf-8") as f:
    data = json.load(f)

words = []
for w in data["words"]:
    if start <= w["start"] < end:
        words.append({
            "word": w["word"],
            "start": round(w["start"] - start, 3),
            "end": round(min(w["end"], end) - start, 3),
        })

seg_starts = [0.0]
for s in data["segment_starts"]:
    if start < s < end:
        seg_starts.append(round(s - start, 3))

with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"words": words, "segment_starts": seg_starts}, f, ensure_ascii=False, indent=2)

print(f"{len(words)} words, {len(seg_starts)} segments, duration {round(end-start,2)}s")
