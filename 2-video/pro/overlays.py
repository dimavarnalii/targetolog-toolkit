"""Графічні накладки поверх змонтованого відео (стиль агента).

Типи (задаються в EDL, поле `overlays`):
  cta_arrows — подвійний шеврон униз під субтитрами на заклику до дії: вилітає великим,
               стискається, далі погойдується до кінця ролика.

`apply()` дописує фрагменти у filter_complex і вхідні файли; повертає нову мітку потоку.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import json
import subprocess

from config import DATA, FFPROBE, IMAGE_EXT, INPUT_BROLL, ROOT, WORK

FX = DATA / "fx"   # генерується при першому використанні

FLASH = 0.4             # світловий спалах, с

CTA_W = {"9x16": 290, "4x5": 240}
CTA_Y = {"9x16": 0.70, "4x5": 0.72}   # центр стрілок, частка висоти
CTA_POP = 0.3
CTA_BOB = 12            # амплітуда погойдування, px
CTA_PERIOD = 0.9


def clip_input(path: Path, start: float, dur: float, fps) -> list[str]:
    """Аргументи ffmpeg для перебивки: відео — з потрібної секунди, фото — зацикленим кадром."""
    if path.suffix.lower() in IMAGE_EXT:
        return ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(path)]
    return ["-ss", str(start), "-t", f"{dur:.3f}", "-i", str(path)]


def is_portrait(path: Path) -> bool:
    """Чи вертикальний кліп (з урахуванням повороту в метаданих телефонних відео)."""
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_side_data=rotation", "-of", "json", str(path)],
                       capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    w, h = st["width"], st["height"]
    rot = next((abs(int(d["rotation"])) for d in st.get("side_data_list", []) if "rotation" in d), 0)
    if rot in (90, 270):
        w, h = h, w
    return h >= w


def kenburns(path: Path, ow: int, oh: int, fps, dur: float, idx: int = 0) -> str:
    """Фото завжди рухається: зум уперед (парні) або назад (непарні) — правило монтажера."""
    if path.suffix.lower() not in IMAGE_EXT:
        return ""
    n = max(1, int(dur * float(fps)))
    z = f"1+0.09*on/{n}" if idx % 2 == 0 else f"1.09-0.09*on/{n}"
    return (f",zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={ow}x{oh}:fps={fps}")


def chevrons_png() -> Path:
    """Два білі шеврони з круглими кінцями і мʼяким світінням (як у референсі)."""
    dst = FX / "cta_chevrons.png"
    if dst.exists():
        return dst
    W, H, stroke, pad = 290, 300, 58, 40
    img = Image.new("RGBA", (W + 2 * pad, H + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = stroke // 2
    for top in (0, 120):
        pts = [(pad + r, pad + top + r), (pad + W // 2, pad + top + 150), (pad + W - r, pad + top + r)]
        d.line(pts, fill=(255, 255, 255, 255), width=stroke, joint="curve")
        for x, y in (pts[0], pts[2], pts[1]):
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255))
    glow = img.filter(ImageFilter.GaussianBlur(14))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(glow)
    out.alpha_composite(img)
    FX.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    return dst


def flash_png(ow: int, oh: int) -> Path:
    """Теплий світловий спалах: білий центр → помаранчевий край."""
    dst = FX / f"flash_{ow}x{oh}.png"
    if dst.exists():
        return dst
    small = Image.new("RGBA", (ow // 8, oh // 8))
    px = small.load()
    cx, cy = small.width * 0.45, small.height * 0.4
    rmax = (small.width ** 2 + small.height ** 2) ** 0.5 * 0.6
    for y in range(small.height):
        for x in range(small.width):
            k = min(1.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / rmax)
            px[x, y] = (255, int(250 - 90 * k), int(235 - 200 * k), int(255 - 70 * k))
    FX.mkdir(parents=True, exist_ok=True)
    small.resize((ow, oh), Image.BICUBIC).save(dst)
    return dst


def ease(p: str) -> str:
    return f"(1-pow(1-({p}),3))"


def apply(overlays, fmt, ow, oh, fps, inputs, filters, cur, base):
    """base — мітка чистого рефреймленого відео (без субтитрів/затемнення) для медіа-зони стрічки."""
    def add_input(*args):
        inputs.extend(args)
        return inputs.count("-i") - 1

    for k, o in enumerate(overlays):
        t0, t1 = o["start"], o["end"]
        tag = f"o{len(filters)}"
        if o["type"] == "cta_arrows":
            w = CTA_W[fmt]
            cy = int(oh * CTA_Y[fmt])
            dur = t1 - t0
            ci = add_input("-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(chevrons_png()))
            pop = f"pow(min(1,max(0,1-(t-{t0:.3f})/{CTA_POP})),2)"
            filters.append(
                f"[{ci}:v]format=rgba,setpts=PTS-STARTPTS+{t0:.3f}/TB,"
                f"scale=w='{w * 370 // 290}*(1+1.4*{pop})':h=-1:eval=frame,"
                f"fade=t=in:st={t0:.3f}:d={CTA_POP * 0.6:.3f}:alpha=1[{tag}a];"
                f"[{cur}][{tag}a]overlay=x='(W-w)/2':"
                f"y='{cy}-h/2+{CTA_BOB}*sin(2*PI*max(0,t-{t0 + CTA_POP:.3f})/{CTA_PERIOD})':"
                f"eof_action=pass[{tag}v]")
            cur = f"{tag}v"
    return cur
