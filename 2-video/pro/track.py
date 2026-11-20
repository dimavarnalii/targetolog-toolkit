"""Трекінг обличчя для рефрейму (окремий процес: cv2 і PyAV з faster-whisper конфліктують).

Детектор — OpenCV YuNet на CPU (mediapipe під macOS вимагає Metal і падає без GPU-сервісу).

Використання: python track.py work/<name>.master.mp4
Результат: work/<name>.faces.json — [[t, cx, cy, h] | [t, null], ...], координати нормовані 0..1
"""
import json
import sys
from pathlib import Path

import cv2

from config import FACE_MODEL, WORK

SAMPLE_FPS = 10
MIN_CONF = 0.7
DETECT_WIDTH = 480  # детектуємо на зменшеному кадрі — швидше і стабільніше


def track(video: Path) -> list:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w0, h0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = DETECT_WIDTH / w0
    size = (DETECT_WIDTH, round(h0 * scale))
    det = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", size, MIN_CONF)

    step = max(1, round(fps / SAMPLE_FPS))
    out, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            _, faces = det.detect(cv2.resize(frame, size))
            t = round(i / fps, 3)
            if faces is not None and len(faces):
                # найбільше обличчя — спікер
                x, y, fw, fh = map(float, max(faces, key=lambda f: f[2] * f[3])[:4])
                out.append([t, round((x + fw / 2) / size[0], 4),
                            round((y + fh / 2) / size[1], 4), round(fh / size[1], 4)])
            else:
                out.append([t, None])
        i += 1
    return out


if __name__ == "__main__":
    video = Path(sys.argv[1])
    name = video.name.removesuffix(".master.mp4")
    faces = track(video)
    (WORK / f"{name}.faces.json").write_text(json.dumps(faces))
    hit = sum(1 for f in faces if f[1] is not None)
    print(f"кадрів: {len(faces)}, з обличчям: {hit} ({hit / max(1, len(faces)):.0%})")
