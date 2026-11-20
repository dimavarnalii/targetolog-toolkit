"""Завантаження моделей, яких немає в пакеті. Лише з прапором --yes (після згоди користувача).

  python fetch_models.py yunet --yes    модель пошуку обличчя OpenCV YuNet (~0,2 МБ, ліцензія MIT) → <дані>/models/
  python fetch_models.py whisper --yes  Whisper large-v3-turbo (~1,6 ГБ) → <дані>/models/whisper (через faster-whisper, Hugging Face)

Куди звертається: raw.githubusercontent.com / github.com (YuNet), huggingface.co (Whisper). Більше нікуди.
YuNet перевіряється за SHA256; невідповідний файл не зберігається.
"""
import argparse
import hashlib
import sys
import urllib.request

from config import FACE_MODEL, WHISPER_DIR, WHISPER_MODEL

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"


def fetch_yunet():
    FACE_MODEL.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(YUNET_URL, headers={"User-Agent": "toolkit-engine/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != YUNET_SHA256:
        sys.exit("✗ SHA256 моделі YuNet не збігається з еталоном: файл не збережено.")
    FACE_MODEL.write_bytes(data)
    print("✓", FACE_MODEL)


def fetch_whisper():
    from faster_whisper import WhisperModel
    WHISPER_DIR.mkdir(parents=True, exist_ok=True)
    WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR))
    print("✓", WHISPER_DIR)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model", choices=["yunet", "whisper"])
    ap.add_argument("--yes", action="store_true", help="підтвердження користувача на завантаження")
    a = ap.parse_args()
    if not a.yes:
        sys.exit("Завантаження лише з прапором --yes (після згоди користувача).")
    fetch_yunet() if a.model == "yunet" else fetch_whisper()
