"""Перевірка дублювання тексту: дубль фрази в звуці («з ними я… з ними я скинула») або слово двічі на стику
склейки / в субтитрах («Все Все»).

Whisper часто «ковтає» повтор: друга копія зникає, а слово перед нею розтягується на 1–2 с. Тому, крім пошуку
однакових фраз у розшифровці, такі розтягнуті слова перерозшифровуються окремим вікном без контексту.

  python repeats.py <відео|words.json|captions.json> [ще файли…]
Код виходу 1, якщо знайдено повтор.
"""
import os
import json
import re
import sys
from pathlib import Path

STOP = set("і й та в у на з із зі до що це я ти ви ми він вона не а як за по від так але чи бо же ж то ну ось".split())
WINDOW = 7.0      # с: повтор далі за цей проміжок — уже риторика, а не дубль
STRETCH = 1.1     # с: слово довше за це (і за 0.14 с на літеру) — підозра на проковтнутий дубль
_model = None


def norm(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower().replace("’", "'")).strip("'")


def load_words(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "words" in data:          # words.json: {"words": [{word, start, end}]}
        return [{"w": x["word"], "s": x["start"], "e": x["end"]} for x in data["words"]]
    if isinstance(data, dict) and "segments" in data:       # transcript.json агента
        return [{"w": x["word"], "s": x["start"], "e": x["end"]} for s in data["segments"] for x in s["words"]]
    return [{"w": x["text"], "s": x["startMs"] / 1000, "e": x["endMs"] / 1000} for x in data]  # captions.json


def model():
    global _model
    if _model is None:
        sys.path.insert(0, str(Path(__file__).parent))
        from faster_whisper import WhisperModel
        from config import WHISPER_DIR, WHISPER_MODEL
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR))
    return _model


def transcribe(audio, offset=0.0, verbatim=False) -> list[dict]:
    segs, _ = model().transcribe(audio, language=os.environ.get("MONTAGE_LANG", "uk"), word_timestamps=True, vad_filter=False,
                                 condition_on_previous_text=False,
                                 initial_prompt="Повторення слів, обмовки." if verbatim else None)
    return [{"w": w.word, "s": w.start + offset, "e": w.end + offset} for s in segs for w in s.words]


def find(words: list[dict]) -> list[tuple[float, float, str]]:
    """(час 1, час 2, фраза) для слів/фраз, що повторюються підряд у межах WINDOW."""
    t = [norm(x["w"]) for x in words]
    hits, used = [], set()
    for n in range(6, 0, -1):
        for i in range(len(t) - n):
            g = t[i:i + n]
            if not all(g) or any(k in used for k in range(i, i + n)):
                continue
            meaningful = [x for x in g if x not in STOP]
            if n == 1 and (not meaningful or len(g[0]) < 3):
                continue
            if n == 2 and not any(len(x) >= 4 for x in meaningful):
                continue
            gap = 1 if n == 1 else 4   # слово — лише впритул («Все Все»); фраза — одразу або через ≤3 слова
            for j in range(i + n, min(len(t) - n + 1, i + n + gap)):
                if t[j:j + n] == g and words[j]["s"] - words[i]["s"] <= WINDOW:
                    hits.append((words[i]["s"], words[j]["s"], " ".join(x["w"].strip() for x in words[i:i + n])))
                    used.update(range(i, i + n), range(j, j + n))
                    break
    return sorted(hits)


def check_media(path: Path) -> list[tuple[float, float, str]]:
    import numpy as np
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(path), sampling_rate=16000)
    words = transcribe(audio)
    hits = find(words)
    for x in words:
        if x["e"] - x["s"] > max(STRETCH, 0.14 * len(norm(x["w"]))):
            # Whisper на тому самому вікні то бачить дубль, то ні — пробуємо кілька початків і обидва режими
            for back, verbatim in ((3.0, False), (2.0, True), (2.0, False), (1.5, True), (3.0, True), (1.0, False)):
                a, b = max(0.0, x["s"] - back), x["e"] + 2.5
                win = transcribe(np.ascontiguousarray(audio[int(a * 16000):int(b * 16000)]), offset=a, verbatim=verbatim)
                new = [h for h in find(win) if not any(abs(h[0] - k[0]) < 1 for k in hits)]
                hits += new
                if new:
                    break
    return sorted(hits)


def check(path) -> list[str]:
    path = Path(path)
    hits = find(load_words(path)) if path.suffix == ".json" else check_media(path)
    return [f"повтор «{p}»: {a:.1f} с і {b:.1f} с" for a, b, p in hits]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    bad = False
    for f in sys.argv[1:]:
        msgs = check(f)
        bad |= bool(msgs)
        print(f"{'✗' if msgs else '✓'} {Path(f).name}: " + ("повторів немає" if not msgs else f"{len(msgs)} повтор(и)"))
        for m in msgs:
            print(f"    {m}")
    sys.exit(1 if bad else 0)
