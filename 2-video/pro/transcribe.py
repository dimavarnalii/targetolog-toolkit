"""Розшифровка відео з таймкодами по словах (faster-whisper).

Використання: python transcribe.py input/raw/video.mp4 [--lang uk]
Результат: work/<name>.transcript.json
"""
import argparse
import json
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

from config import FFMPEG, WHISPER_DIR, WHISPER_MODEL, WORK

MODEL = WHISPER_MODEL
# Дослівна розшифровка: без підказки Whisper «прибирає» вигуки й фальстарти з тексту, але лишає їх у звуці —
# і склейка захоплює «і…», «ну», «а потім… потім». Підказка в розмовному стилі змушує записувати їх словами,
# тож «мозок» бачить їх і вирізає (перевірено на приклад: знайдено «і…», «ну», «а потім…», «він»).
VERBATIM_PROMPT = {"uk": "Е-е, ну... і, і тоді я... м-м, тобто... а потім, потім ми... хм, так от.",
                   "ru": "Э-э, ну... и, и тогда я... м-м, то есть... а потом, потом мы... хм, вот."}


def extract_audio(video: Path, wav: Path) -> None:
    subprocess.run(
        [FFMPEG, "-loglevel", "error", "-y", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )


def transcribe(video: Path, lang: str | None) -> Path:
    work = WORK
    work.mkdir(parents=True, exist_ok=True)
    wav = work / f"{video.stem}.wav"
    extract_audio(video, wav)

    model = WhisperModel(MODEL, device="cpu", compute_type="int8",
                         download_root=str(WHISPER_DIR))
    segments, info = model.transcribe(
        str(wav), language=lang, word_timestamps=True,
        vad_filter=False,  # паузи потрібні нам у таймкодах, не вирізаємо їх тут
        condition_on_previous_text=False,  # інакше Whisper «згладжує» дублі й запинки
        hotwords=VERBATIM_PROMPT.get(lang or "uk"),  # на кожне 30-с вікно; initial_prompt діє лише на перше
    )

    out = {"source": str(video), "language": info.language, "verbatim": True,
           "duration": info.duration, "segments": []}
    for s in segments:
        out["segments"].append({
            "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
            "words": [{"w": w.word.strip(), "start": round(w.start, 3),
                       "end": round(w.end, 3), "p": round(w.probability, 3)}
                      for w in (s.words or [])],
        })
        print(f"[{s.start:7.2f} → {s.end:7.2f}] {s.text.strip()}", flush=True)

    dst = work / f"{video.stem}.transcript.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--lang", default=None, help="uk / ru / en; без параметра — автовизначення")
    a = ap.parse_args()
    print("→", transcribe(a.video, a.lang))
