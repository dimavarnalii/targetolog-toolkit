"""Вирізати фразу з готового ролика (або лишити тільки її) — точно по словах і по кадрах.

  python cut_phrase.py <відео> --from "не нужен большой капитал" --to "вы знаете что я уже" [--keep] [--lang ru]

- `--from` — перші слова фрази, яку прибираємо; `--to` — перші слова того, що має йти ПІСЛЯ вирізаного (його лишаємо).
  Без `--to` — вирізати до кінця речення, що починається з `--from`.
- `--keep` — навпаки: лишити тільки шматок [from, to) (кліп).
- Межі «прилипають» до найближчої зміни кадру (±0.45 с): у готових креативах фраза часто — окремий вклеєний кадр
  з плашкою/субтитром, і різ по слову лишає 2–10 кадрів чужої плашки. Якщо зміна кадру — посеред переходу
  (спалах/поворот), різ стає рівно по межі вставки, і перехід змикається сам.
- Вихід поруч: `<назва>_cut.mp4`. Потім ОБОВ'ЯЗКОВО подивись кадри навколо стику (скрипт друкує команду) і
  перерозпізнай 3 с навколо стику — чи не обрізане слово.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FFMPEG = os.environ.get("VM_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("VM_FFPROBE") or shutil.which("ffprobe") or "ffprobe"



def _load_audio(path):
    """Аудіо 16 кГц mono float32 через ffmpeg (без faster_whisper.decode_audio: на деяких ПК PyAV у ній падає)."""
    import shutil
    import subprocess
    import numpy as np
    ff = os.environ.get("VM_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
    raw = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def norm(s):
    return re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))


def words_of(path, lang):
    from faster_whisper import WhisperModel
    m = WhisperModel(os.environ.get("VM_WHISPER_MODEL", "large-v3-turbo"), device="cpu", compute_type="int8")
    segs, _ = m.transcribe(_load_audio(path), language=lang, word_timestamps=True)
    return [{"t": w.word.strip(), "s": w.start, "e": w.end} for s in segs for w in s.words]


def find(words, phrase, after=0):
    q = [norm(x) for x in phrase.split() if norm(x)]
    for i in range(after, len(words) - len(q) + 1):
        if [norm(w["t"]) for w in words[i:i + len(q)]] == q:
            return i
    # м'якший пошук: перші 3 слова з префіксом 4 літери (Whisper плутає закінчення)
    q3 = [x[:4] for x in q[:3]]
    for i in range(after, len(words) - len(q3) + 1):
        if [norm(w["t"])[:4] for w in words[i:i + len(q3)]] == q3:
            return i
    sys.exit(f"не знайшов у розшифровці: «{phrase}»")


def scene_cuts(path, a, b):
    log = subprocess.run([FFMPEG, "-hide_banner", "-ss", str(max(0, a)), "-t", str(b - a), "-i", str(path),
                          "-vf", "select='gt(scene,0.25)',showinfo", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return [max(0, a) + float(x) for x in re.findall(r"pts_time:([\d.]+)", log)]


def snap(path, t, lo, hi):
    """Найближча зміна кадру до t у межах [lo, hi]; інакше t."""
    cuts = [c for c in scene_cuts(path, t - 0.45, t + 0.45) if lo <= c <= hi]
    return min(cuts, key=lambda c: abs(c - t)) if cuts else t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--from", dest="frm", required=True)
    ap.add_argument("--to")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--lang")
    a = ap.parse_args()
    src = Path(a.video)
    v = json.loads(subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=r_frame_rate:format=duration", "-of", "json", str(src)],
                                  capture_output=True, text=True, check=True).stdout)
    n, d = v["streams"][0]["r_frame_rate"].split("/")
    fps = int(n) / int(d)
    dur = float(v["format"]["duration"])
    W = words_of(src, a.lang)
    i = find(W, a.frm)
    if a.to:
        j = find(W, a.to, i + 1)
    else:
        j = next((k + 1 for k in range(i, len(W)) if re.search(r"[.!?]$", W[k]["t"])), len(W))
    prev_end = W[i - 1]["e"] if i else 0.0
    start_word = W[i]["s"]
    next_start = W[j]["s"] if j < len(W) else dur
    last_end = W[j - 1]["e"]
    a_t = snap(src, (prev_end + start_word) / 2, prev_end, start_word)
    b_t = snap(src, (last_end + next_start) / 2, last_end, next_start) if j < len(W) else dur
    fa, fb = round(a_t * fps), round(b_t * fps)        # різ рівно по кадрах
    a_t, b_t = fa / fps, fb / fps
    print(f"вирізаю {'(лишаю) ' if a.keep else ''}{a_t:.3f}–{b_t:.3f} с: «{' '.join(w['t'] for w in W[i:j])}»")
    out = src.with_name(src.stem + "_cut.mp4")
    if a.keep:
        fc = (f"[0:v]trim=start_frame={fa}:end_frame={fb},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[v];"
              f"[0:a]atrim={a_t}:{b_t},asetpts=PTS-STARTPTS,afade=t=in:d=0.02,afade=t=out:st={b_t - a_t - 0.03:.3f}:d=0.03[a]")
    else:
        fc = (f"[0:v]trim=end_frame={fa},setpts=PTS-STARTPTS[v1];[0:v]trim=start_frame={fb},setpts=PTS-STARTPTS[v2];"
              f"[0:a]atrim=0:{a_t},asetpts=PTS-STARTPTS,afade=t=out:st={max(0, a_t - 0.02):.3f}:d=0.02[a1];"
              f"[0:a]atrim=start={b_t},asetpts=PTS-STARTPTS,afade=t=in:d=0.02[a2];"
              f"[v1][a1][v2][a2]concat=n=2:v=1:a=1[vc][a];[vc]setsar=1,format=yuv420p[v]")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", "9M", "-bufsize", "18M",
                    "-r", v["streams"][0]["r_frame_rate"], "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-colorspace", "bt709", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    print("✓", out)
    if not a.keep:
        print(f'перевір стик: ffmpeg -ss {max(0, a_t - 0.3):.2f} -t 0.6 -i "{out}" -vf "fps=30,scale=130:-2,tile=9x2" '
              f'-frames:v 1 join.jpg')


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
