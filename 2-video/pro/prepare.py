"""Підготовка сирого відео до монтажу.

1. Знаходить тишу (ffmpeg silencedetect) — Whisper часто «розтягує» слова на паузи,
   тому реальні паузи беремо з аудіо, а не з таймкодів слів.
2. Будує нумерований текст по словах для того, хто приймає монтажні рішення
   (зараз — Claude у сесії, далі — виклик API).

Використання: python prepare.py work/<name>.transcript.json
Результат: work/<name>.silence.json, work/<name>.words.txt
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from config import FFMPEG, WORK

SILENCE_DB = -35
SILENCE_MIN = 0.2


def detect_silence(video: str) -> list[list[float]]:
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", video, "-vn",
         "-af", f"silencedetect=n={SILENCE_DB}dB:d={SILENCE_MIN}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    out, start = [], None
    for line in r.stderr.splitlines():
        if m := re.search(r"silence_start: ([\d.]+)", line):
            start = float(m.group(1))
        elif (m := re.search(r"silence_end: ([\d.]+)", line)) and start is not None:
            out.append([round(start, 3), round(float(m.group(1)), 3)])
            start = None
    return out


def flatten_words(tr: dict) -> list[dict]:
    words = []
    for s in tr["segments"]:
        for w in s["words"]:
            words.append({"i": len(words), **w})
    return words


def words_listing(words: list[dict], silences: list[list[float]]) -> str:
    """Текст виду `[12.40] 57:вот 58:мы ‖0.9s 59:позицию` — індекс слова, паузи ≥0.4с."""
    def pause_before(t: float) -> float:
        return max((min(e, t) - s for s, e in silences if s < t <= e + 0.15), default=0)

    lines, cur = [], []
    for w in words:
        gap = pause_before(w["start"]) if cur else 0
        if cur and (gap >= 0.8 or len(cur) >= 14):
            lines.append(" ".join(cur))
            cur = []
        if not cur:
            cur.append(f"[{w['start']:.2f}]")
        if gap >= 0.4:
            cur.append(f"‖{gap:.1f}s")
        low = "?" if w["p"] < 0.5 else ""
        cur.append(f"{w['i']}:{w['w']}{low}")
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


if __name__ == "__main__":
    tr_path = Path(sys.argv[1])
    tr = json.loads(tr_path.read_text())
    name = tr_path.name.removesuffix(".transcript.json")
    sil = detect_silence(tr["source"])
    words = flatten_words(tr)
    (WORK / f"{name}.silence.json").write_text(json.dumps(sil))
    listing = words_listing(words, sil)
    (WORK / f"{name}.words.txt").write_text(listing)
    print(f"words: {len(words)}, silences: {len(sil)}, "
          f"total silence: {sum(e - s for s, e in sil):.1f}s of {tr['duration']:.1f}s")
