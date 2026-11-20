"""Субтитри на готове відео: розпізнати мову → сторінки по 2–3 слова КАПСОМ, поточне слово жовтим → вшити.

  python burn_subs.py <відео> [--lang uk] [--fix "погане=добре" …] [--size 52] [--bottom 0.26] [--font <ttf>]
  python burn_subs.py <відео> --ass-only       # лише .ass + .words.json поруч, щоб перевірити й поправити текст

Вихід — поруч: `<назва>_субтитри.mp4`, звук не перекодовується. Оригінал не чіпається.
Обов'язково прочитай .words.json / друк сторінок і виправ помилки розпізнавання (`--fix`): назви брендів,
імена, схожі слова («волюром» → «велюром»). «Дякую за перегляд!» на тиші в кінці — галюцинація Whisper, скрипт її викидає.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = os.environ.get("VM_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("VM_FFPROBE") or shutil.which("ffprobe") or "ffprobe"
HALLUCINATIONS = ("дякую за перегляд", "спасибо за просмотр", "продолжение следует", "субтитры")



def _load_audio(path):
    """Аудіо 16 кГц mono float32 через ffmpeg (без faster_whisper.decode_audio: на деяких ПК PyAV у ній падає)."""
    import shutil
    import subprocess
    import numpy as np
    ff = os.environ.get("VM_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
    raw = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(path: Path, lang):
    from faster_whisper import WhisperModel
    m = WhisperModel(os.environ.get("VM_WHISPER_MODEL", "large-v3-turbo"), device="cpu", compute_type="int8")
    segs, info = m.transcribe(_load_audio(path), language=lang, word_timestamps=True)
    words = []
    for s in segs:
        if any(h in s.text.lower() for h in HALLUCINATIONS):
            continue
        words += [{"t": w.word.strip(), "s": w.start, "e": w.end} for w in s.words]
    return words, info.language


def tidy(words, fixes):
    out = []
    for w in words:
        t = w["t"]
        core = re.sub(r"[.,!?:;…]+$", "", t)
        t = fixes.get(core.lower(), core) + t[len(core):]
        if out and t[:1] in "'ʼ’":                       # Whisper рве «м'якому» на «м» + «'якому»
            out[-1]["t"] += "ʼ" + t[1:]
            out[-1]["e"] = w["e"]
            continue
        out.append({**w, "t": t})
    return out


def pages(words, max_words=3, max_chars=16, gap=0.35):
    res, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (len(cur) >= max_words or len(" ".join(x["t"] for x in cur)) >= max_chars
                or re.search(r"[.,!?–—:;]$", w["t"]) or not nxt or nxt["s"] - w["e"] > gap):
            res.append(cur)
            cur = []
    return res


def ts(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def build_ass(pg, w, h, size, bottom, font_name):
    hl, white = r"{\c&H00D7FF&}", r"{\c&HFFFFFF&}"     # жовтий (BGR) / білий
    clean = lambda t: re.sub(r"[.,!?:;–—…]+$", "", t).strip().upper()  # noqa: E731
    out = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2", "",
           "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
           "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
           "MarginR, MarginV, Encoding",
           f"Style: Cap,{font_name},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,"
           f"{max(3, size // 10)},2,2,{w // 18},{w // 18},{int(h * bottom)},1", "",
           "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for pi, p in enumerate(pg):
        end = p[-1]["e"] + 0.25
        if pi + 1 < len(pg):
            end = min(end, pg[pi + 1][0]["s"])
        for k, x in enumerate(p):
            a = x["s"]
            b = p[k + 1]["s"] if k + 1 < len(p) else end
            text = " ".join(hl + clean(y["t"]) + white if j == k else clean(y["t"]) for j, y in enumerate(p))
            out.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{text}")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--lang", default=None, help="uk/ru/en…; без нього — автовизначення")
    ap.add_argument("--fix", action="append", default=[], help='"погане=добре" (без розділових знаків)')
    ap.add_argument("--size", type=int, help="px шрифту (дефолт ≈ 7.2 %% ширини кадру)")
    ap.add_argument("--bottom", type=float, default=0.26, help="відступ знизу, частка висоти")
    ap.add_argument("--font", help="ttf (дефолт: Montserrat-Black.ttf з папки fonts/ поруч, інакше Arial)")
    ap.add_argument("--ass-only", action="store_true")
    a = ap.parse_args()
    src = Path(a.video)
    m = json.loads(subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "json", str(src)],
                                  capture_output=True, text=True, check=True).stdout)["streams"][0]
    w, h = m["width"], m["height"]
    words, lang = transcribe(src, a.lang)
    words = tidy(words, {k.lower(): v for k, v in (f.split("=", 1) for f in a.fix)})
    pg = pages(words)
    print(f"мова: {lang}; сторінок: {len(pg)}")
    print(" | ".join(" ".join(x["t"] for x in p) for p in pg))
    font = Path(a.font) if a.font else next((p for p in [
        Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Montserrat-Black.ttf",
        Path.cwd() / "fonts" / "Montserrat-Black.ttf"] if p.exists()), None)
    ass = build_ass(pg, w, h, a.size or round(w * 0.072), a.bottom, "Montserrat Black" if font else "Arial")
    stem = src.with_suffix("")
    if a.ass_only:
        Path(str(stem) + ".ass").write_text(ass, encoding="utf-8")
        Path(str(stem) + ".words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        print("✓", str(stem) + ".ass")
        return
    out = Path(str(stem) + "_субтитри.mp4")
    with tempfile.TemporaryDirectory() as tmp:          # ffmpeg-фільтр subtitles не любить кирилицю/емодзі/двокрапки в шляхах
        t = Path(tmp)
        shutil.copy2(src, t / ("in" + src.suffix))
        (t / "subs.ass").write_text(ass, encoding="utf-8")
        (t / "fonts").mkdir()
        if font:
            shutil.copy2(font, t / "fonts" / font.name)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", "in" + src.suffix, "-vf", "subtitles=subs.ass:fontsdir=fonts",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                        "-c:a", "copy", "-movflags", "+faststart", "out.mp4"], cwd=tmp, check=True)
        shutil.copy2(t / "out.mp4", out)
    print("✓", out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
