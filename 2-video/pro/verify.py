"""Перевірка склейки на слух: розпізнає готовий майстер заново і порівнює зі сценарієм.

Ловить те, що Whisper приховав у першій розшифровці: заповнювачі («і», «а»), фальстарти («потім… потім»),
обрізані слова. Друкує розбіжності з часом у майстрі (без хука).
  python verify.py приклад work/приклад.txt
"""
import os
import difflib
import json
import re
import sys

from faster_whisper import WhisperModel

from config import WHISPER_DIR, WHISPER_MODEL, WORK


def norm(t: str) -> list[str]:
    t = re.sub(r"\s+(['-])", r"\1", t.lower().replace("’", "'"))  # «з 'їсти», «онлайн -ефір» → одне слово
    return re.sub(r"[^\w'-]", " ", t).split()


if __name__ == "__main__":
    name, script = sys.argv[1], sys.argv[2]
    m = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR))
    from transcribe import VERBATIM_PROMPT  # дослівно: інакше Whisper «не чує» вигуків, які ми й шукаємо
    segs, _ = m.transcribe(str(WORK / f"{name}.master.mp4"), language=os.environ.get("MONTAGE_LANG", "uk"), word_timestamps=True,
                           condition_on_previous_text=False, hotwords=VERBATIM_PROMPT.get(os.environ.get("MONTAGE_LANG", "uk"), VERBATIM_PROMPT["uk"]))
    heard = [(w.word, w.start, w.end) for s in segs for w in s.words]
    got = [norm(w)[0] if norm(w) else "" for w, _, _ in heard]
    ref = norm(open(script, encoding="utf-8").read())
    sm = difflib.SequenceMatcher(a=ref, b=got, autojunk=False)
    issues, found = 0, []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            continue
        t = heard[b0][1] if b0 < len(heard) else heard[-1][1]
        exp, act = " ".join(ref[a0:a1]), " ".join(got[b0:b1])
        if op == "delete" and a0 > 0 and a1 < len(ref) or op != "delete":
            issues += 1
            t_end = heard[b1 - 1][2] if b1 > b0 else t
            found.append({"t": round(t, 2), "t_end": round(t_end, 2), "op": op, "script": exp, "heard": act})
            print(f"{t:6.2f} с  {op:7}  сценарій: «{exp}»  чути: «{act}»")
    print(f"розбіжностей: {issues}")
    (WORK / f"{name}.verify.json").write_text(json.dumps(found, ensure_ascii=False))  # для сторінки перегляду
