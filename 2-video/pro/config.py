"""Спільні шляхи й налаштування Pro-монтажу.

Код рушія лежить у папці рушія (ROOT). Усі ДАНІ (проміжні файли, результати, моделі) лежать у папці користувача:
  MONTAGE_DATA   (за замовчуванням <VM_ROOT>/engine; VM_ROOT за замовчуванням ~/ad-montage)
    input/raw/   сирі відео
    work/        проміжні файли кожного кроку (кеш: повторний запуск продовжує з місця зупинки)
    output/      готові ролики
    models/      моделі (Whisper, YuNet); завантажуються лише за згодою користувача
  Бібліотека перебивок: <VM_ROOT>/library (catalog.json з описами, див. 2-video/ad_creatives/library_catalog.py)
Моделі можна тримати окремо: MONTAGE_MODELS=<папка>.
"""
import os
import pathlib as _pl
import shutil as _sh
import sys as _sys
from pathlib import Path

# UTF-8 скрізь: на Windows консоль і файли за замовчуванням у cp1251, а тексти (укр.) у UTF-8
for _st in (_sys.stdout, _sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
_rt, _wt = _pl.Path.read_text, _pl.Path.write_text
_pl.Path.read_text = lambda self, encoding=None, errors=None: _rt(self, encoding or "utf-8", errors)
_pl.Path.write_text = lambda self, data, encoding=None, errors=None, newline=None: _wt(self, data, encoding or "utf-8", errors)

ROOT = Path(__file__).resolve().parent
VM_ROOT = Path(os.environ.get("VM_ROOT") or (Path.home() / "ad-montage")).expanduser()
DATA = Path(os.environ.get("MONTAGE_DATA") or (VM_ROOT / "engine")).expanduser()

# ffmpeg з libass (для субтитрів). VM_FFMPEG/VM_FFPROBE або PATH. На macOS звичайний Homebrew-ffmpeg без libass:
# потрібен ffmpeg-full (brew install ffmpeg-full).
_mac_full = "/opt/homebrew/opt/ffmpeg-full/bin/"
FFMPEG = os.environ.get("VM_FFMPEG") or (_mac_full + "ffmpeg" if _sys.platform == "darwin" and Path(_mac_full + "ffmpeg").exists()
                                         else (_sh.which("ffmpeg") or "ffmpeg"))
FFPROBE = os.environ.get("VM_FFPROBE") or (_mac_full + "ffprobe" if _sys.platform == "darwin" and Path(_mac_full + "ffprobe").exists()
                                           else (_sh.which("ffprobe") or "ffprobe"))
# апаратний кодек Apple лише на Mac; інакше libx264
VENC = "h264_videotoolbox" if _sys.platform == "darwin" else "libx264"
# Windows: npx це npx.cmd; дочірні Python-процеси в UTF-8 (інакше українські тексти ламаються cp1251)
NPX = _sh.which("npx") or "npx"
PY = _sys.executable
os.environ.setdefault("PYTHONUTF8", "1")

MODELS = Path(os.environ.get("MONTAGE_MODELS") or (DATA / "models")).expanduser()
os.environ.setdefault("TORCH_HOME", str(MODELS / "torch"))


def ff_path(p) -> str:
    """Шлях для аргументу фільтра ffmpeg: на Windows «D:\\…» ламає розбір (двокрапка, зворотні скісні)."""
    s = Path(p).as_posix()
    return s.replace(":", "\\:") if _sys.platform == "win32" else s


WHISPER_MODEL = os.environ.get("MONTAGE_WHISPER", "large-v3-turbo")
LANG = os.environ.get("MONTAGE_LANG", "uk")   # мова відео: run.py виставляє з --lang для всіх кроків
WHISPER_DIR = MODELS / "whisper"
FACE_MODEL = MODELS / "face_detection_yunet.onnx"  # OpenCV YuNet, CPU

FONTS_DIR = ROOT / "fonts"   # Montserrat (SIL OFL), кладеться поруч із кодом
DEFAULT_FONT = "Montserrat"

INPUT_RAW = DATA / "input" / "raw"
INPUT_BROLL = VM_ROOT / "library"   # та сама бібліотека, що в ad_creatives/library_catalog.py
WORK = DATA / "work"
OUTPUT = DATA / "output"
for _d in (INPUT_RAW, WORK, OUTPUT):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def out_find(name: str) -> Path:
    """Файл з output/: спершу в корені, потім у підпапках."""
    p = OUTPUT / name
    return p if p.exists() else next(OUTPUT.rglob(name), p)


def out_glob(pattern: str) -> list:
    """Як OUTPUT.glob, але й по підпапках; однакові назви — береться перша знайдена."""
    seen = {}
    for p in sorted(OUTPUT.glob(pattern)) + sorted(OUTPUT.rglob(pattern)):
        seen.setdefault(p.name, p)
    return sorted(seen.values(), key=lambda p: p.name)


import contextlib as _cl
import tempfile as _tf
import types as _types


@_cl.contextmanager
def tmpwav():
    """Тимчасовий wav-шлях. NamedTemporaryFile на Windows не можна відкрити вдруге (ffmpeg: Permission denied)."""
    with _tf.TemporaryDirectory() as d:
        yield _types.SimpleNamespace(name=str(Path(d) / "t.wav"))


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# Експорт: H.264, Rec.709, бітрейт 5–10 Мбіт/с (вище лише для 4K)
ENCODE_V = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", "10M", "-bufsize", "20M",
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
ENCODE = ENCODE_V + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]


def out_fps(src_fps: float) -> int:
    """fps готового відео залежить від зйомки (25 → 25, 30 → 30); 50/60 зі смартфона зводимо до 25/30."""
    return round(src_fps) if src_fps <= 30.5 else round(src_fps / 2)
