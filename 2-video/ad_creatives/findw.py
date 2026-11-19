"""findw.py NAME word1 word2 ... -> start times + context of matching words (run from the project folder)"""
import json, sys
from pathlib import Path

P = Path.cwd()  # run from the project folder
ws = json.loads((P / f"{sys.argv[1]}.words_m.json").read_text(encoding="utf-8"))["words"]
targets = [t.lower() for t in sys.argv[2:]]
for i, w in enumerate(ws):
    if w["word"].lower().strip(".,!?") in targets:
        ctx = " ".join(x["word"] for x in ws[max(0, i - 2):i + 3])
        print(f"{w['start']:7.2f}-{w['end']:6.2f}  {w['word']:<14} | {ctx}")
