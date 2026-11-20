"""Адаптивний кольорокор і затемнення під текст.

Монтажер: кольорокор робиться у Premiere під вихідник («коригуються тіні, світло, контраст; показники щоразу
різні»); віньєтка до 5% і рідко; затемнення (10–20%) кладеться між відео й текстом, ТІЛЬКИ коли текст зливається
з фоном. Тому тут немає одного фіксованого «вигляду»: фільтр рахується зі статистики самого відео.
"""
import math
import re
import statistics
import subprocess

from config import FFMPEG


def _stats(video: str, vf: str, seconds: int = 45) -> dict:
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-t", str(seconds), "-i", video, "-an",
         "-vf", f"{vf}fps=2,signalstats,metadata=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True)
    vals: dict[str, list[float]] = {"YLOW": [], "YAVG": [], "YHIGH": []}
    for line in r.stdout.splitlines():
        m = re.search(r"lavfi\.signalstats\.(YLOW|YAVG|YHIGH)=([\d.]+)", line)
        if m:
            vals[m.group(1)].append(float(m.group(2)))
    return {k: statistics.median(v) for k, v in vals.items() if v}


def grade_filter(video: str) -> str:
    """Обережне вирівнювання: середня яскравість до ~46%, контраст p10–p90 до ~[40, 210]. Без зсуву кольору."""
    s = _stats(video, "")
    if len(s) < 3:
        return "null"
    a = min(max(s["YAVG"] / 255, 0.08), 0.92)
    gamma = math.log(a) / math.log(0.463)          # eq: gamma > 1 освітлює середні тони
    gamma = min(max(1 + (gamma - 1) * 0.5, 0.88), 1.18)   # лише половина поправки
    span = max(s["YHIGH"] - s["YLOW"], 40)
    contrast = min(max((210 - 40) / span, 0.95), 1.12)
    return f"eq=contrast={contrast:.3f}:gamma={gamma:.3f}"


def dim_alpha(video: str) -> float:
    """Яке затемнення (0…0.2) покласти під субтитри: 0, якщо фон у зоні тексту темний і текст читається."""
    s = _stats(video, "crop=iw:ih*0.3:0:ih*0.4,")
    if not s:
        return 0.0
    y = s["YAVG"]
    return round(min(0.2, max(0.0, (y - 120) / 50 * 0.2)), 3)


def dim_layer_pgm(ow: int, oh: int, alpha: float, centre: float, dst) -> None:
    """PGM-альфа: мʼяка смуга затемнення навколо рядка субтитрів (centre — частка висоти кадру)."""
    half = 0.09 * oh
    c = centre * oh
    rows = bytes(int(255 * alpha * max(0.0, 1 - ((y - c) / half) ** 2)) for y in range(oh))
    dst.write_bytes(f"P5 1 {oh} 255\n".encode() + rows)
