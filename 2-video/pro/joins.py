"""Контроль стиків: де склеєно різні шматки мови і чи помітно це глядачу.

Для кожного стику рахує, скільки вирізано (з таймлайну склейки), і як змінюється картинка у вікні кадрування:
розмір обличчя, різниця кадрів до/після, яскравість. Правило монтажера: місця, де мову сильно різали, обов'язково
перекривати перебивкою. Відкриті помітні стики агент виправляє сам:
  • перебивка поруч (≤0,6 с) — подовжує її на стик;
  • інакше — «наїзд»: після стику кадр на 12% ближче (стрибок виглядає навмисним, прийом монтажерів);
  • стрибок яскравості — вирівнює шматок після стику.
"""
import subprocess

import numpy as np

from config import FFMPEG

CUT_BIG = 1.0        # вирізано більше — «сильно різали» (різні дублі, викинуте речення)
DIFF_JUMP = 0.11     # середня різниця кадрів у вікні (0..1), вище — стрибок видно
FACE_JUMP = 0.07     # зміна розміру обличчя, вище — видно
LUMA_JUMP = 0.06     # зміна яскравості, вище — видно
TAKE_GAP = 10.0      # між шматками вирізано більше — це вже інший дубль (інша експозиція можлива)
NEAR_BROLL = 0.6     # перебивку ближче за це до стику подовжуємо, щоб закрити його
ZOOM = 1.12


def covered_at(broll: list, t: float, before: float = 0.02, after: float = 0.15, off: float = 0.0) -> bool:
    """Чи закритий момент t перебивками — з урахуванням суміжних (одна закінчується, наступна одразу починається)."""
    spans = sorted((b["start"] + off, b["start"] + b["dur"] + off) for b in broll)
    a, need = t - before, t + after
    for s, e in spans:
        if s <= a + 1e-3 and e > a:
            a = e
        if a >= need:
            return True
    return False


def frame_gray(video: str, t: float, crop: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = crop
    raw = subprocess.run([FFMPEG, "-loglevel", "error", "-ss", f"{max(0, t):.3f}", "-i", video, "-frames:v", "1",
                          "-vf", f"crop={w}:{h}:{x}:{y},scale=72:128,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).astype(float).reshape(128, 72) / 255 if len(raw) == 72 * 128 else None


def face_at(faces: list, t: float, before: bool):
    """Найближчий вимір обличчя до стику з потрібного боку (до 0,4 с)."""
    cand = [f for f in faces if f[1] is not None and (t - 0.4 <= f[0] < t if before else t <= f[0] <= t + 0.4)]
    if not cand:
        return None
    return max(cand, key=lambda f: f[0]) if before else min(cand, key=lambda f: f[0])


def check(master: str, fps: float, cuts: list, timeline: list, off: float, path: list, cw: int, ch: int,
          faces: list, broll: list, total: float) -> tuple[list, list, list]:
    """Повертає (звіт по стиках, наїзди [[t0,t1,z]], поправки яскравості [[t0,t1,gain]]); broll змінює на місці."""
    def crop_at(t):
        pts = [p for p in path if p[0] <= t]
        p = pts[-1] if pts else path[0]
        return int(p[1]), int(p[2]), cw, ch

    report, zooms, gains = [], [], []
    for k in range(1, len(timeline)):
        t = timeline[k]["dst_start"] + off
        removed = timeline[k]["src_start"] - timeline[k - 1]["src_end"]
        if removed <= 0.02:
            continue  # межа фрази для темпу, а не стик (відео безперервне)
        a = frame_gray(master, t - 1.5 / fps, crop_at(t - 0.01))
        b = frame_gray(master, t + 0.5 / fps, crop_at(t + 0.01))
        diff = float(np.abs(a - b).mean()) if a is not None and b is not None else 0.0
        luma = float(b.mean() / max(1e-3, a.mean()) - 1) if a is not None and b is not None else 0.0
        fa, fb = face_at(faces, t, True), face_at(faces, t, False)
        face = abs(fb[3] / fa[3] - 1) if fa and fb else 0.0
        visible = diff > DIFF_JUMP or face > FACE_JUMP or abs(luma) > LUMA_JUMP
        big = removed > CUT_BIG
        covered = covered_at(broll, t)
        action = "закрито перебивкою" if covered else "ок"
        if not covered and (visible or big):
            nxt = min((x for x in broll if 0 <= x["start"] - t <= NEAR_BROLL), key=lambda x: x["start"], default=None)
            prv = max((x for x in broll if 0 <= t - (x["start"] + x["dur"]) <= NEAR_BROLL),
                      key=lambda x: x["start"], default=None)
            # не залазимо на попередню перебивку
            prev_end = max([x["start"] + x["dur"] for x in broll if x is not nxt and x["start"] < t] + [0])
            gap_prev = max((x for x in broll if x is not nxt and x["start"] < t), key=lambda x: x["start"] + x["dur"],
                           default=None)
            if nxt is not None and gap_prev is not None and nxt["start"] - (gap_prev["start"] + gap_prev["dur"]) < 0.5:
                # стик у короткій щілині між двома перебивками — просто змикаємо їх
                gap_prev["dur"] = nxt["start"] - gap_prev["start"]
                action = "зімкнено перебивки"
            elif nxt is not None and prev_end <= t - 0.04:
                nxt["dur"] += nxt["start"] - (t - 0.04)
                nxt["start"] = t - 0.04
                action = "подовжено перебивку назад"
            elif prv is not None:
                prv["dur"] = t + 0.2 - prv["start"]
                action = "подовжено перебивку вперед"
            else:
                end = min([x["start"] for x in broll if x["start"] > t] + [timeline[k + 1]["dst_start"] + off
                          if k + 1 < len(timeline) else total, total])
                zooms.append([round(t, 3), round(end, 3), ZOOM])
                action = "наїзд після стику"
        report.append({"k": k, "t": round(t, 2), "removed": round(removed, 2), "diff": round(diff, 3), "face": round(face, 3),
                       "luma": round(luma, 3), "action": action})
    # яскравість: вирівнюємо ДУБЛІ, а не шматки. Усередині дубля «різниця» — це руки й волосся у вікні, не світло.
    # Дубль = шматки, між якими вирізано < TAKE_GAP с. Різницю між дублями міряємо на кадрах біля їх стику
    # (найближча сцена), потім усі дублі приводимо до найдовшого.
    takes = [[0]]
    for k in range(1, len(timeline)):
        if timeline[k]["src_start"] - timeline[k - 1]["src_end"] > TAKE_GAP:
            takes.append([])
        takes[-1].append(k)
    if len(takes) > 1:
        lum_join = {r["k"]: r["luma"] for r in report}
        level = [1.0]  # яскравість дубля відносно першого
        for ti in range(1, len(takes)):
            level.append(level[-1] * (1 + lum_join.get(takes[ti][0], 0.0)))
        span = lambda ks: (timeline[ks[0]]["dst_start"] + off,
                           timeline[ks[-1] + 1]["dst_start"] + off if ks[-1] + 1 < len(timeline) else total)
        main = max(range(len(takes)), key=lambda i: span(takes[i])[1] - span(takes[i])[0])
        for ti, ks in enumerate(takes):
            g = level[main] / level[ti]
            if abs(g - 1) > LUMA_JUMP:
                t0, t1 = span(ks)
                gains.append([round(t0, 3), round(t1, 3), round(g, 3)])
                report.append({"k": None, "t": round(t0, 2), "removed": 0, "diff": 0, "face": 0, "luma": round(1 / g - 1, 3),
                               "action": f"дубль вирівняно за яскравістю ×{g:.2f}"})
    return report, zooms, gains
