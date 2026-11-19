# -*- coding: utf-8 -*-
"""Voice track for a TTS avatar / clean voiceover: a simple ffmpeg voice chain (no AI denoiser: a TTS voice has no noise to remove),
plus optional slowdown.

Usage: python avatar_audio.py <video|audio> <out.wav> [--speed 0.9] [--target -14] [--presence 4]

Chain: mono, 80 Hz high-pass, EQ (mud -2 dB @220, presence +N dB @3.2k, air +1.5 dB @7k),
compressor 3:1, two-pass loudnorm to target LUFS, then atempo=speed (pitch preserved).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_config as cfg  # noqa: E402

FFMPEG = cfg.FFMPEG


def run(cmd, capture=False):
    r = subprocess.run([str(c) for c in cmd], check=True, capture_output=capture, text=True, encoding="utf-8", errors="replace")
    return r.stderr if capture else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--target", type=float, default=-14)
    ap.add_argument("--presence", type=float, default=4)
    a = ap.parse_args()

    chain = ("pan=mono|c0=0.5*c0+0.5*c1,highpass=f=80:poles=2,"
             f"equalizer=f=220:t=q:w=1.2:g=-2,equalizer=f=3200:t=q:w=1.0:g={a.presence},"
             "equalizer=f=7000:t=h:w=0.7:g=1.5,"
             "acompressor=threshold=-24dB:ratio=3:attack=8:release=150:makeup=2")
    lt = f"loudnorm=I={a.target}:TP=-1.5:LRA=9"
    err = run([FFMPEG, "-hide_banner", "-nostats", "-i", a.src, "-map", "0:a:0", "-af",
               f"{chain},{lt}:print_format=json", "-f", "null", "-"], capture=True)
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S).group(0))
    ln = (f"{lt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    tempo = f",atempo={a.speed}" if a.speed != 1.0 else ""
    run([FFMPEG, "-v", "error", "-y", "-i", a.src, "-map", "0:a:0", "-af",
         f"{chain},{ln},aresample=48000{tempo}", "-c:a", "pcm_s16le", a.out])
    print(f"wrote {a.out} (input {m['input_i']} LUFS -> {a.target}, speed {a.speed})")


if __name__ == "__main__":
    main()
