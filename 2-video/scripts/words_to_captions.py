# -*- coding: utf-8 -*-
"""Whisper/stable-ts words JSON -> Remotion Caption[] JSON (@remotion/captions), source timing.

Usage: python words_to_captions.py <words.json> <captions.json> [--fix "печала=почала" ...]

Accepts {"words": [...]} or a bare list of {word, start, end}. Each caption text gets a leading
space (createTikTokStyleCaptions is whitespace-sensitive). Slowdown is applied in the
composition (SPEED), not here.
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words")
    ap.add_argument("out")
    ap.add_argument("--fix", action="append", default=[], help="wrong=right, substring replace")
    a = ap.parse_args()

    d = json.load(open(a.words, encoding="utf-8"))
    words = d["words"] if isinstance(d, dict) else d
    fixes = [f.split("=", 1) for f in a.fix]
    out = []
    for w in words:
        t = w["word"].strip()
        for bad, good in fixes:
            t = t.replace(bad, good)
        s, e = round(w["start"] * 1000), round(w["end"] * 1000)
        out.append({"text": " " + t, "startMs": s, "endMs": e, "timestampMs": (s + e) // 2, "confidence": None})
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(out)} captions -> {a.out}")


if __name__ == "__main__":
    main()
