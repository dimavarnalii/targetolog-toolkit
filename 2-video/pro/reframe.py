"""Кадрування горизонтальних перебивок у вертикаль за об'єктом — замість «вписати + розмиті поля».

Для кожного кліпу шукає, де головне: обличчя (YuNet) або, якщо облич немає, найпомітніша область
(OpenCV saliency). Повертає горизонтальний центр кадру в часі; шаблон Remotion ставить туди вікно cover.
Кадруємо лише за обличчям; без обличчя (спина, крупний план шва) і коли люди не влазять у вертикальне вікно
(кілька людей по краях) — лишаємо розмиті поля.

Окремий процес (cv2 не вантажимо поруч із PyAV).
  python reframe.py work/_reframe_in.json work/_reframe_out.json
  вхід: [{"key": ..., "path": ..., "kind": "photo|video", "t0": 0, "t1": 3.2, "aspect": 0.5625}]
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from config import FACE_MODEL

SAMPLE_FPS = 4      # для відео: стільки кадрів на секунду аналізуємо
MIN_CONF = 0.6
FACE_SHARE = 0.6    # обличчя має знайтись хоча б у такій частці кадрів, інакше — saliency


def frames(path: str, kind: str, t0: float, t1: float):
    if kind == "photo":
        img = cv2.imread(path)
        if img is not None:
            yield 0.0, img
        return
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    t = t0
    while t <= max(t0, t1):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        if not ok:
            break
        yield t - t0, img
        t += 1 / SAMPLE_FPS
    cap.release()


def faces(img, det) -> list[tuple[float, float, float]]:
    """[(центр x 0..1, ширина 0..1, впевненість)] облич на кадрі."""
    h, w = img.shape[:2]
    scale = 640 / max(w, h)
    small = cv2.resize(img, (int(w * scale), int(h * scale)))
    det.setInputSize((small.shape[1], small.shape[0]))
    _, found = det.detect(small)
    out = []
    for f in found if found is not None else []:
        x, y, fw, fh, conf = f[0], f[1], f[2], f[3], f[-1]
        if conf >= MIN_CONF and fw * fh >= 0.0006 * small.shape[0] * small.shape[1]:
            out.append(((x + fw / 2) / small.shape[1], fw / small.shape[1], float(conf)))
    return out


def salient_x(img, sal) -> tuple[float, float]:
    """Центр і «ширина» (2σ) помітної області по горизонталі, 0..1."""
    small = cv2.resize(img, (320, int(320 * img.shape[0] / img.shape[1])))
    if sal is None:  # opencv без contrib — saliency недоступний, центр кадру
        return 0.5, 1.0
    ok, m = sal.computeSaliency(small)
    if not ok:
        return 0.5, 1.0
    col = m.mean(axis=0)
    col = np.clip(col - np.percentile(col, 30), 0, None)
    if col.sum() <= 0:
        return 0.5, 1.0
    xs = np.linspace(0, 1, len(col))
    c = float((xs * col).sum() / col.sum())
    sd = float(np.sqrt(((xs - c) ** 2 * col).sum() / col.sum()))
    return c, 2 * sd


def analyze(item: dict, det, sal) -> dict:
    v = item["aspect"] / (item["srcW"] / item["srcH"])  # яку частку ширини кадру видно у вертикальному вікні
    track, spans, hits, n = [], [], 0, 0
    for t, img in frames(item["path"], item["kind"], item.get("t0", 0), item.get("t1", 0)):
        n += 1
        fs = faces(img, det)
        if fs:
            hits += 1
            xs = [f[0] for f in fs]
            # кілька облич — центр групи, ширина групи
            track.append((t, (min(xs) + max(xs)) / 2))
            spans.append(max(xs) - min(xs) + max(f[1] for f in fs))
        else:
            track.append((t, None))
    method = "face" if n and hits / n >= FACE_SHARE else "saliency"
    if method == "saliency":
        track, spans = [], []
        for t, img in frames(item["path"], item["kind"], item.get("t0", 0), item.get("t1", 0)):
            c, wdt = salient_x(img, sal)
            track.append((t, c))
            spans.append(wdt)
    # дірки (кадри без обличчя) — тримаємо останню відому позицію; згладжування медіаною з 5
    last = next((x for _, x in track if x is not None), 0.5)
    filled = []
    for t, x in track:
        last = x if x is not None else last
        filled.append([round(t, 2), last])
    xs = [x for _, x in filled]
    sm = [float(np.median(xs[max(0, i - 2):i + 3])) for i in range(len(xs))]
    path = [[t, round(x, 4)] for (t, _), x in zip(filled, sm)]
    span = float(np.median(spans)) if spans else 1.0
    # влазить: об'єкт (або група облич) займає не більше ~90% видимого вікна; для saliency — суворіше
    # без обличчя не кадруємо: saliency на шві (bar_14) обрала візерунок одягу — краще розмиті поля
    fits = method == "face" and span <= 0.9 * v
    return {"key": item["key"], "method": method, "span": round(span, 3), "visible": round(v, 3),
            "fits": bool(fits), "path": path}


if __name__ == "__main__":
    items = json.loads(Path(sys.argv[1]).read_text())
    det = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (320, 320), MIN_CONF)
    sal = cv2.saliency.StaticSaliencySpectralResidual_create() if hasattr(cv2, "saliency") else None
    out = [analyze(it, det, sal) for it in items]
    Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False))
    for o in out:
        print(f"  {o['key']}: {o['method']}, об'єкт {o['span']:.0%} ширини, видно {o['visible']:.0%} → "
              f"{'кадруємо' if o['fits'] else 'лишаємо розмиті поля'}")
