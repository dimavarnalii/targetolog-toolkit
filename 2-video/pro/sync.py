"""Синхрон субтитрів зі звуком: остання перевірка після склейки, перед рендером.

Межі слів беруться з вирівнювання сирого відео; на окремих ділянках воно помиляється (приклад, перший дубль:
субтитри на 0,4–0,66 с пізніше за звук), і з самих даних цього не видно. Тому розпізнаємо готовий майстер,
зіставляємо кожне слово склейки з почутим (по тексту), рахуємо розходження й згладжуємо медіаною по сусідніх
словах. Де стабільне розходження > MIN_SHIFT — зсуваємо слова, а з ними перебивки й накладки (вони прив'язані
до слів). Поодинокий шум таймінгів розпізнавання (±0,1 с) не чіпаємо.
  python sync.py <name>
"""
import os
import difflib
import json
import sys

import numpy as np

from config import WHISPER_DIR, WHISPER_MODEL, WORK
from verify import norm

MIN_SHIFT = 0.2
WINDOW = 7


def heard_words(master: str) -> list[tuple[str, float]]:
    from faster_whisper import WhisperModel
    from transcribe import VERBATIM_PROMPT
    m = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR))
    segs, _ = m.transcribe(master, language=os.environ.get("MONTAGE_LANG", "uk"), word_timestamps=True, condition_on_previous_text=False,
                           hotwords=VERBATIM_PROMPT.get(os.environ.get("MONTAGE_LANG", "uk"), VERBATIM_PROMPT["uk"]))
    return [(norm(w.word)[0] if norm(w.word) else "", w.start) for s in segs for w in s.words]


if __name__ == "__main__":
    name = sys.argv[1]
    cut_path = WORK / f"{name}.cut.json"
    cut = json.loads(cut_path.read_text())
    words = [w for w in cut["words"] if norm(w["w"])]
    heard = heard_words(cut["master"])
    a = [norm(w["w"])[0] for w in words]
    b = [h for h, _ in heard]
    pairs, onset = [], {}
    for blk in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            pairs.append((words[blk.a + k]["start"], heard[blk.b + k][1] - words[blk.a + k]["start"]))
            onset[blk.a + k] = heard[blk.b + k][1]
    # окреме слово після паузи: протяжний початок («схуу-днути») вирівнювання ставить пізно, сусіди при цьому
    # точні — згладжування такого не бачить. Якщо слово звучить раніше на >0,25 с і цей момент у паузі перед
    # ним, переносимо початок (група субтитрів і перебивка на ньому з'являться разом зі звуком)
    fixed = []
    for i, w in enumerate(words):
        h = onset.get(i)
        prev_end = words[i - 1]["end"] if i else 0.0
        if h is not None and w["start"] - h > 0.25 and h >= prev_end - 0.02:
            fixed.append((w["w"], w["start"], h))
            for b_ in cut.get("broll", []):
                if abs(b_["start"] - w["start"]) < 0.05:
                    b_["dur"] = round(b_["dur"] + (b_["start"] - h), 3)
                    b_["start"] = round(h, 3)
            w["start"] = round(h, 3)
    if len(pairs) < 5:
        print("  замало збігів для перевірки синхрону")
        sys.exit(0)
    t = np.array([p[0] for p in pairs])
    d = np.array([p[1] for p in pairs])
    smooth = np.array([np.median(d[max(0, i - WINDOW // 2):i + WINDOW // 2 + 1]) for i in range(len(d))])
    shift = np.where(np.abs(smooth) > MIN_SHIFT, smooth, 0.0)
    at = lambda x: float(np.interp(x, t, shift))  # зсув у будь-який момент (між зіставленими словами — інтерпольовано)
    moved = int((shift != 0).sum())
    if fixed:
        print("  початок слів перенесено на реальний звук: "
              + ", ".join(f"«{w}» {s0:.2f}→{h:.2f}" for w, s0, h in fixed))
    if not moved:
        if fixed:
            cut_path.write_text(json.dumps(cut, ensure_ascii=False, indent=1))
        print(f"  синхрон у нормі: медіана {np.median(d) * 1000:+.0f} мс, 90% ≤ {np.percentile(abs(d), 90) * 1000:.0f} мс")
        sys.exit(0)
    for w in cut["words"]:
        dd = at(w["start"])
        w["start"], w["end"] = round(w["start"] + dd, 3), round(w["end"] + dd, 3)
    for b_ in cut.get("broll", []):
        b_["start"] = round(b_["start"] + at(b_["start"]), 3)
    for o in cut.get("overlays", []):
        dd = at(o["start"])
        o["start"] = round(o["start"] + dd, 3)
        if o.get("end") is not None:
            o["end"] = round(o["end"] + dd, 3)
        if o.get("broll_start") is not None:
            o["broll_start"] = round(o["broll_start"] + at(o["broll_start"]), 3)
    cut_path.write_text(json.dumps(cut, ensure_ascii=False, indent=1))
    zones = []
    for i in range(len(t)):
        if shift[i] and (not zones or t[i] - zones[-1][1] > 1.0):
            zones.append([t[i], t[i], shift[i]])
        elif shift[i]:
            zones[-1][1] = t[i]
    print("  субтитри зсунуто під звук: " + "; ".join(f"{z0:.1f}–{z1:.1f} с на {s * 1000:+.0f} мс" for z0, z1, s in zones))
