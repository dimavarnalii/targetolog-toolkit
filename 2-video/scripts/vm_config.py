# -*- coding: utf-8 -*-
"""Спільні налаштування всіх скриптів пакета. Жодних зашитих шляхів: усе береться зі змінних
середовища або має розумні значення за замовчуванням.

Змінні середовища (усі необов'язкові, крім випадку, коли ffmpeg не в PATH):
  VM_ROOT          робоча папка (за замовчуванням ~/ad-montage); у ній sources/ projects/ done/ library/
  VM_FFMPEG        повний шлях до ffmpeg (якщо його немає в PATH)
  VM_FFPROBE       повний шлях до ffprobe (якщо немає в PATH)
  VM_MUSIC         ваш музичний трек (mp3/wav) — без нього музики в рендері не буде
  VM_WHOOSH        ваш звук whoosh для перебивок — без нього звуків не буде
  VM_BANNER        картинка-плашка (webp/png), що виїжджає знизу в шортсах — без неї плашки не буде
  VM_OUTRO_CARD    картинка кінцівки для шортсів — без неї кінцівки не буде
  VM_ASS_FONT      назва шрифта для субтитрів/хуків (за замовчуванням "Arial Black"); має бути встановлений у системі
  VM_FONTS_DIR     папка з .ttf, якщо шрифт не встановлено в систему (ffmpeg ass: fontsdir)
  VM_FONT_FILE     повний шлях до .ttf для підписів на контактних листах (drawtext); авто-пошук, якщо не задано
  VM_WHISPER_MODELS папка кешу моделей faster-whisper (за замовчуванням — стандартний кеш)
  VM_BRAND         назва підпапки в done/<дата>/ для креативів (за замовчуванням "creatives")
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(os.environ.get("VM_ROOT") or (Path.home() / "ad-montage"))
SOURCES = ROOT / "sources"
PROJECTS = ROOT / "projects"
DONE = ROOT / "done"
LIBRARY = ROOT / "library"

FFMPEG = os.environ.get("VM_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("VM_FFPROBE") or shutil.which("ffprobe") or "ffprobe"
PY = sys.executable  # той самий Python, де встановлено faster-whisper


def _opt_file(name):
    v = os.environ.get(name)
    return v if v and Path(v).exists() else None


MUSIC = _opt_file("VM_MUSIC")
WHOOSH = _opt_file("VM_WHOOSH")
BANNER = _opt_file("VM_BANNER")
OUTRO_CARD = _opt_file("VM_OUTRO_CARD")
ASS_FONT = os.environ.get("VM_ASS_FONT") or "Arial Black"
FONTS_DIR = os.environ.get("VM_FONTS_DIR") or None
WHISPER_MODELS = os.environ.get("VM_WHISPER_MODELS") or None
BRAND = os.environ.get("VM_BRAND") or "creatives"


def _find_font_file():
    v = os.environ.get("VM_FONT_FILE")
    if v and Path(v).exists():
        return v
    for c in (r"C:\Windows\Fonts\arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(c).exists():
            return c
    return None


FONT_FILE = _find_font_file()


def ff_path(p):
    """Шлях для вставки всередину ffmpeg-фільтра (drawtext fontfile=, ass=): слеші прямі, двокрапка екранована."""
    return str(p).replace("\\", "/").replace(":", "\\:")


def drawtext_font_opt():
    """Фрагмент "fontfile='...':" для drawtext або порожній рядок (тоді ffmpeg візьме шрифт за замовчуванням)."""
    return f"fontfile='{ff_path(FONT_FILE)}':" if FONT_FILE else ""


def ass_filter(path):
    """Фільтр ass=... з урахуванням VM_FONTS_DIR."""
    f = f"ass='{ff_path(path)}'"
    if FONTS_DIR:
        f += f":fontsdir='{ff_path(FONTS_DIR)}'"
    return f


def ffmpeg_major():
    import re
    import subprocess
    try:
        out = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True).stdout
        m = re.search(r"version\D*(\d+)", out)
        return int(m.group(1)) if m else 0
    except OSError:
        return 0


def filter_script_args(path):
    """Аргументи ffmpeg для довгого графа з файлу. У нових збірках -filter_complex_script прибрано
    (замість нього -/filter_complex). Межа версій НЕ ПЕРЕВІРЕНА автором — див. README."""
    if ffmpeg_major() >= 7:
        return ["-/filter_complex", str(path)]
    return ["-filter_complex_script", str(path)]


def check_environment():
    """Повертає список проблем (порожній = все гаразд). Скрипти НІЧОГО не встановлюють самі."""
    import subprocess
    problems = []
    for name, exe in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
        try:
            subprocess.run([exe, "-version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            problems.append(f"{name} не знайдено ({exe}). Встановіть ffmpeg і додайте в PATH або задайте VM_FFMPEG/VM_FFPROBE.")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        problems.append("Python-пакет faster-whisper не встановлено: pip install faster-whisper numpy")
    return problems


if __name__ == "__main__":
    print("ROOT        :", ROOT)
    print("FFMPEG      :", FFMPEG, "(major", ffmpeg_major(), ")")
    print("FFPROBE     :", FFPROBE)
    print("PYTHON      :", PY)
    print("MUSIC       :", MUSIC or "— (не задано, музики не буде)")
    print("WHOOSH      :", WHOOSH or "— (не задано, звуків перебивок не буде)")
    print("BANNER      :", BANNER or "— (плашки в шортсах не буде)")
    print("OUTRO_CARD  :", OUTRO_CARD or "— (кінцівки в шортсах не буде)")
    print("ASS_FONT    :", ASS_FONT, "| FONTS_DIR:", FONTS_DIR or "—")
    print("FONT_FILE   :", FONT_FILE or "— (підписи на листах без явного шрифта)")
    probs = check_environment()
    for p in probs:
        print("ПРОБЛЕМА:", p)
    sys.exit(1 if probs else 0)
