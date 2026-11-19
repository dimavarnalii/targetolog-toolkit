"""Word-level transcription with faster-whisper.

Usage: transcribe_words.py audio16k.wav words.json [--model small|medium] [--lang ru|uk|..] [--prompt "..."]
Input must be 16 kHz mono PCM WAV (ffmpeg -ar 16000 -ac 1 -c:a pcm_s16le).
Output: {"words": [{word,start,end}], "segment_starts": [...], "text": "...", "language": "ru"}
"""
import argparse
import json
import os
import wave

import numpy as np
from faster_whisper import WhisperModel

ap = argparse.ArgumentParser()
ap.add_argument("wav")
ap.add_argument("out_json")
ap.add_argument("--model", default="small")
ap.add_argument("--lang", default=None)
ap.add_argument("--prompt", default=None, help="initial_prompt: names/terms to spell correctly")
args = ap.parse_args()

with wave.open(args.wav, "rb") as wf:
    assert wf.getframerate() == 16000
    assert wf.getnchannels() == 1
    frames = wf.readframes(wf.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

model = WhisperModel(args.model, device="cpu", compute_type="int8", download_root=os.environ.get("VM_WHISPER_MODELS") or None)

segments, info = model.transcribe(audio, beam_size=5, word_timestamps=True,
                                  language=args.lang, initial_prompt=args.prompt)

words = []
seg_bounds = []
full_text = []
for seg in segments:
    seg_bounds.append(seg.start)
    full_text.append(seg.text.strip())
    for w in seg.words:
        words.append({"word": w.word.strip(), "start": w.start, "end": w.end})

with open(args.out_json, "w", encoding="utf-8") as f:
    json.dump({"words": words, "segment_starts": seg_bounds, "text": " ".join(full_text),
               "language": info.language}, f, ensure_ascii=False, indent=2)

print(f"Words: {len(words)}, segments: {len(seg_bounds)}, language: {info.language}")
