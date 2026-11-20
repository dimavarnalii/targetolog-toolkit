"""Контроль якості готового ролика перед відправкою — те, що монтажер перевіряє очима й вухами.

Технічні вимоги монтажера: H.264, yuv420p, Rec.709, ≤10 Мбіт/с, 1080×1920 (9:16) або 1080×1350 (4:5).
Звук: гучність −16 LUFS (±1,5), пік ≤ −1 dBTP. Картинка: без чорних кадрів і «застиглих» шматків, звук без
провалів, текст без дублів (repeats.py, лише 9:16). Друкує зведення і код виходу 1, якщо є помилки (не попередження).

  python qa.py output/приклад.mp4 [ще файли…]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from config import FFMPEG, FFPROBE

SIZES = {(1080, 1920): "9x16", (1080, 1350): "4x5"}
LUFS, LUFS_TOL, PEAK_MAX = -16.0, 1.5, -1.0
MAX_RATE = 10_000_000


def probe(path: str) -> dict:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                        "format=duration,bit_rate:stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,"
                        "color_primaries,color_transfer,color_space,bit_rate", "-of", "json", path],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def filters_log(path: str, af: str | None = None, vf: str | None = None) -> str:
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", path]
    cmd += ["-af", af] if af else ["-an"]
    cmd += ["-vf", vf] if vf else ["-vn"]
    cmd += ["-f", "null", "-"]
    return subprocess.run(cmd, capture_output=True, text=True).stderr


def check(path: str) -> dict:
    errors, warns, info = [], [], {}
    meta = probe(path)
    v = next((s for s in meta["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in meta["streams"] if s["codec_type"] == "audio"), None)
    dur = float(meta["format"]["duration"])
    info["тривалість"] = round(dur, 2)
    if not v:
        errors.append("немає відео")
    else:
        fmt = SIZES.get((v["width"], v["height"]))
        info["формат"] = fmt or f"{v['width']}×{v['height']}"
        if not fmt:
            errors.append(f"розмір {v['width']}×{v['height']} — не 9:16 і не 4:5")
        if v["codec_name"] != "h264":
            errors.append(f"кодек {v['codec_name']}, потрібен H.264")
        if v.get("pix_fmt") != "yuv420p":
            errors.append(f"pix_fmt {v.get('pix_fmt')}, потрібен yuv420p")
        tags = [v.get("color_primaries"), v.get("color_transfer"), v.get("color_space")]
        if any(t not in (None, "unknown") and t != "bt709" for t in tags) or all(t in (None, "unknown") for t in tags):
            warns.append(f"колір не позначено як Rec.709 ({'/'.join(str(t) for t in tags)})")
        n, d = v["r_frame_rate"].split("/")
        info["к/с"] = round(int(n) / int(d), 2)
    rate = int(meta["format"].get("bit_rate", 0))
    info["бітрейт, Мбіт/с"] = round(rate / 1e6, 2)
    if rate > MAX_RATE:
        errors.append(f"бітрейт {rate / 1e6:.1f} Мбіт/с > 10")
    if not a:
        errors.append("немає звуку")
    else:
        log = filters_log(path, af="ebur128=peak=true")
        m = re.search(r"Integrated loudness:\s+I:\s+(-?[\d.]+) LUFS", log)
        p = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+) dBFS", log)
        if m:
            info["гучність, LUFS"] = float(m.group(1))
            if abs(float(m.group(1)) - LUFS) > LUFS_TOL:
                warns.append(f"гучність {m.group(1)} LUFS (ціль {LUFS})")
        if p:
            info["пік, dBTP"] = float(p.group(1))
            if float(p.group(1)) > PEAK_MAX:
                warns.append(f"пік {p.group(1)} dBTP > {PEAK_MAX}")
        sil = re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_duration: ([\d.]+)",
                         filters_log(path, af="silencedetect=n=-45dB:d=1.2"))
        for s, d in sil:
            warns.append(f"тиша {float(d):.1f} с з {float(s):.1f} с")
    if v:
        blk = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)",
                         filters_log(path, vf="blackdetect=d=0.12:pix_th=0.06"))
        for s, e in blk:
            (errors if float(s) > 0.05 else warns).append(f"чорні кадри {float(s):.2f}–{float(e):.2f} с")
        frz = re.findall(r"freeze_start: ([\d.]+)[\s\S]*?freeze_duration: ([\d.]+)",
                         filters_log(path, vf="freezedetect=n=0.002:d=1.5"))
        for s, d in frz:
            warns.append(f"картинка стоїть {float(d):.1f} с з {float(s):.1f} с")
        # дубль фрази в звуці («з ними я… з ними я скинула», 30.10); 4:5 має той самий звук — лише 9:16
        if info.get("формат") == "9x16":
            from repeats import check as repeats
            errors += repeats(path)
    res = {"file": Path(path).name, "ok": not errors, "errors": errors, "warnings": warns, "info": info}
    # звіт лише в лог: .qa.json поруч із роликами людині заважають (14.10)
    return res


if __name__ == "__main__":
    bad = False
    for f in sys.argv[1:]:
        r = check(f)
        bad |= not r["ok"]
        print(f"{'✓' if r['ok'] else '✗'} {r['file']}: " + ", ".join(f"{k} {v}" for k, v in r["info"].items()))
        for e in r["errors"]:
            print(f"    помилка: {e}")
        for w in r["warnings"]:
            print(f"    увага: {w}")
    sys.exit(1 if bad else 0)
