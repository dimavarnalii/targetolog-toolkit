# -*- coding: utf-8 -*-
"""Word-level transcript with the `medium` model (more accurate than small), no VAD.

Usage (run from the project folder, after make_proxies.py):
    python transcribe_medium.py --lang uk IMG_0001 IMG_0002 ...
For each name N: takes ./proxy/N.mp4 -> N.wav (16 kHz mono, made here if missing) -> N.words_m.json
Output: {"words": [{word,start,end}], "segment_starts": [...]}
"""
import argparse
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vm_config as vm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("names", nargs="+")
ap.add_argument("--lang", required=True, help="мова відео: uk, ru, en ...")
ap.add_argument("--model", default="medium")
a = ap.parse_args()

model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=4,
                     download_root=os.environ.get("VM_WHISPER_MODELS") or None)
for n in a.names:
    wav = Path(f"{n}.wav")
    if not wav.exists():
        subprocess.run([vm.FFMPEG, "-v", "error", "-y", "-i", str(Path("proxy") / f"{n}.mp4"), "-vn",
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
    with wave.open(str(wav), "rb") as wf:
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(audio, language=a.lang, beam_size=5, word_timestamps=True,
                                      vad_filter=False, condition_on_previous_text=False)
    words, seg_bounds = [], []
    for seg in segments:
        seg_bounds.append(seg.start)
        for w in seg.words:
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    with open(f"{n}.words_m.json", "w", encoding="utf-8") as f:
        json.dump({"words": words, "segment_starts": seg_bounds}, f, ensure_ascii=False, indent=1)
    print(n, len(words), flush=True)
