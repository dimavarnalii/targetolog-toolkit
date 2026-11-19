"""For each gap > 0.7s in medium transcript, show what the small model heard there.
Needs N.words_m.json (transcribe_medium.py) AND N.words.json (scripts/transcribe_words.py on N.wav, model small).
Usage (from the project folder): python gapcheck.py IMG_0001 [...]"""
import json, sys
from pathlib import Path

P = Path.cwd()  # run from the project folder
for n in sys.argv[1:]:
    m = json.loads((P / f"{n}.words_m.json").read_text(encoding="utf-8"))["words"]
    s = json.loads((P / f"{n}.words.json").read_text(encoding="utf-8"))["words"]
    print("#####", n)
    for a, b in zip(m, m[1:]):
        g0, g1 = a["end"], b["start"]
        if g1 - g0 > 0.7:
            heard = [w["word"] for w in s if w["start"] >= g0 - 0.05 and w["end"] <= g1 + 0.05]
            if heard:
                print(f"  {g0:6.2f}-{g1:6.2f} ({g1 - g0:.1f}s): {' '.join(heard)}")
