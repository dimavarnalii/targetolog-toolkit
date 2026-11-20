"""Перевірка на слух, що сама виправляє: зайві вигуки, які verify.py почув у склейці, вирізаються з сирого відео.

verify.py розпізнає готову склейку заново й порівнює зі сценарієм. Вставку з коротких «зайвих» слів
(«і», «ну», «а», «м-м» — plan.SMALL_EXTRA) переводимо з часу склейки в час сирого відео (таймлайн склейки
з прискоренням кожного шматка), розширюємо межі до тиші (не різати сусідні слова) і дописуємо в
cut_times монтажного листа. Інші розбіжності лише показуємо — їх вирішує людина.
  python autofix.py <name>      # друкує, що додано; код 0 — додано, 1 — нічого виправляти
"""
import os
import json
import re
import sys

import numpy as np

from config import WORK
from cut import load_rms
from plan import SMALL_EXTRA, _norm


def to_source(timeline: list, t: float) -> float:
    k = max((i for i, p in enumerate(timeline) if p["dst_start"] <= t + 1e-6), default=0)
    p = timeline[k]
    return p["src_start"] + (t - p["dst_start"]) * p.get("speed", 1.0)


def to_quiet(rms, t: float, forward: bool, limit: float = 0.15) -> float:
    """Від межі вигуку — до найближчої тиші (не далі limit): щоб не захопити сусіднє слово й не лишити хвіст."""
    r, step = rms
    quiet = 0.08 * float(np.percentile(r, 90))
    i, lim = int(t / step), int((t + (limit if forward else -limit)) / step)
    while (i < lim if forward else i > lim) and 0 <= i < len(r) and r[i] > quiet:
        i += 1 if forward else -1
    return i * step


def fixes(name: str) -> list[list[float]]:
    found = json.loads((WORK / f"{name}.verify.json").read_text())
    cut = json.loads((WORK / f"{name}.cut.json").read_text())
    rms = load_rms(WORK / f"{name}.wav")
    tr = json.loads((WORK / f"{name}.transcript.json").read_text())
    words = [w for s in tr["segments"] for w in s["words"]]
    out = []
    for d in found:
        heard = [_norm(w) for w in d["heard"].split()]
        if d["op"] != "insert" or not heard or len(heard) > 2 or not all(w in SMALL_EXTRA for w in heard):
            continue
        s0 = to_source(cut["timeline"], d["t"])
        s1 = to_source(cut["timeline"], d.get("t_end", d["t"]))
        # час розпізнавання склейки неточний (±0,3 с): самі вигуки шукаємо в дослівній розшифровці сирого відео,
        # де вони є словами з точними межами, і ріжемо рівно їх — не заходячи в сусідні слова
        mid = lambda w: (w["start"] + w["end"]) / 2
        idx = [i for i, w in enumerate(words) if s0 - 0.35 <= mid(w) <= s1 + 0.35 and _norm(w["w"]) in SMALL_EXTRA]
        if not idx:
            continue  # у розшифровці такого вигуку немає — показати людині, не різати навмання
        i0, i1 = min(idx), max(idx)
        lo = words[i0 - 1]["end"] + 0.02 if i0 > 0 else 0.0
        hi = words[i1 + 1]["start"] - 0.02 if i1 + 1 < len(words) else words[i1]["end"] + 0.5
        a = max(lo, to_quiet(rms, words[i0]["start"], forward=False))
        b = min(hi, to_quiet(rms, words[i1]["end"], forward=True))
        if b - a < 0.04 or b - a > 1.2:
            continue
        out.append([round(a, 3), round(b, 3)])
        print(f"  вирізаю «{d['heard']}» ({d['t']:.2f} с у склейці → {a:.2f}–{b:.2f} с у сирому)")
    return out


ABBREV = {"кг", "км", "грн", "тис", "млн", "см", "м"}


def _quiet_run(r, step: float, t0: float, t1: float, quiet: float) -> int:
    """Найдовша послідовність тихих кадрів (10 мс) у [t0, t1]."""
    best = cur = 0
    for v in r[int(t0 / step):int(t1 / step)]:
        cur = cur + 1 if v < quiet else 0
        best = max(best, cur)
    return best


HALLUC = ("дякую", "субтитр", "продовження", "підписуйтесь", "редактор", "коректор")


def gap_fixes(name: str) -> list[list[float]]:
    """Мова в проміжку між двома СУСІДНІМИ збереженими словами, якої немає в розшифровці: Whisper «склеїв»
    фальстарт чи вигук із сусіднім словом («ти заганяєшся… заганяєш» → одне «заганяєш», «разів м-м більше»),
    і ні «мозок», ні перевірка склейки їх не бачать — а в звуці вони є (приклад: шість таких місць).
    Кожен такий шматок розпізнаємо окремо: слова → вирізати; тиша/подих (розпізнавання «вигадує» «Дякую»,
    «Субтитрувальниця») → лишити; звук, покритий межами Whisper попереднього слова, — його ж хвіст, лишити."""
    import subprocess
    import tempfile
    from config import FFMPEG
    tr = json.loads((WORK / f"{name}.transcript.json").read_text())
    words = [w for s in tr["segments"] for w in s["words"]]
    edl = json.loads((WORK / f"{name}.edl.json").read_text())
    kept = sorted({i for a, b in edl["keep"] for i in range(a, b + 1)})
    rms = load_rms(WORK / f"{name}.wav")
    r, step = rms
    loud = 0.15 * float(np.percentile(r, 90))
    reliable = lambda w: "whisper" not in w or w.get("a", 0) >= 0.6
    cache_f = WORK / f"{name}.gaps.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    model, out = None, []
    for i, j in zip(kept, kept[1:]):
        if j != i + 1:
            continue
        a_, b_ = words[i], words[j]
        g0 = a_["end"] if reliable(a_) else min(a_["end"], a_["whisper"][1])
        g1 = b_["start"] if reliable(b_) else max(b_["start"], b_["whisper"][0])
        if g1 - g0 < 0.3:
            continue
        seg = r[int(g0 / step):int(g1 / step)]
        idx = np.where(seg > loud)[0]
        if idx.size * step < 0.25:
            continue
        v0, v1 = g0 + idx[0] * step, g0 + (idx[-1] + 1) * step
        if "whisper" in a_ and a_["whisper"][1] >= v1 - 0.05:
            continue  # звук під межами Whisper попереднього слова — це його ж хвіст
        # числа й скорочення звучать довше, ніж записані: «80 кг» = «вісімдесят кілограмів» — «проміжок» після
        # «кг» — це «-рамів», а не вставка
        if any(re.search(r"\d", w["w"]) or _norm(w["w"]) in ABBREV for w in (a_, b_)):
            continue
        # межі невпевнено вирівняного сусіда невідомі: вставкою вважаємо лише звук, відділений від нього тишею
        # («-два» (0,14) тягнеться без паузи в «м-» слова «місяць» — це не вставка; «ти» (0,5) → пауза → «заганяєшся»)
        quiet = 0.08 * float(np.percentile(r, 90))
        sep = lambda t0, t1: _quiet_run(r, step, t0, t1, quiet) >= 3
        if not reliable(a_) and not sep(min(a_["start"], a_["whisper"][0]), v0):
            continue
        if not reliable(b_) and not sep(v1, max(b_["end"], b_["whisper"][1])):
            continue
        key = f"{v0:.2f}-{v1:.2f}"
        if key not in cache:
            if model is None:
                from faster_whisper import WhisperModel
                from config import WHISPER_DIR, WHISPER_MODEL
                from transcribe import VERBATIM_PROMPT
                model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR))
            from config import tmpwav
            with tmpwav() as f:
                subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-ss", f"{max(0, v0 - 0.03):.3f}", "-to", f"{v1 + 0.03:.3f}",
                                "-i", str(WORK / f"{name}.wav"), "-af", "adelay=300,apad=pad_dur=0.6", f.name], check=True)
                segs, _ = model.transcribe(f.name, language=os.environ.get("MONTAGE_LANG", "uk"), hotwords=VERBATIM_PROMPT.get(os.environ.get("MONTAGE_LANG", "uk"), VERBATIM_PROMPT["uk"]),
                                           condition_on_previous_text=False, word_timestamps=True)
                segs = list(segs)
                # час слів — від початку шматка (мінус тиша 0,3 с, додана спереду, і запас 0,03 с)
                cache[key] = {"text": " ".join(x.text for x in segs).strip(),
                              "words": [[x.word.strip(), round(x.start - 0.3 - 0.03, 3), round(x.end - 0.3 - 0.03, 3)]
                                        for sg in segs for x in (sg.words or [])]}
            cache_f.write_text(json.dumps(cache, ensure_ascii=False))
        entry = cache[key] if isinstance(cache[key], dict) else {"text": cache[key], "words": []}
        text, gw = entry["text"], entry["words"]
        if not _norm(text.replace(" ", "")) or any(h in text.lower() for h in HALLUC):
            continue
        # межа різу — до тиші; для невпевнено вирівняного сусіда його «кінець» неточний (у «ти» на 0,1 с пізніше
        # за справжній), тож дозволяємо дійти до тиші, але не далі середини самого слова
        lo = g0 + 0.02 if reliable(a_) else (min(a_["start"], a_["whisper"][0]) + a_["end"]) / 2
        hi = g1 - 0.02 if reliable(b_) else (b_["start"] + max(b_["end"], b_["whisper"][1])) / 2
        a = max(lo, to_quiet(rms, v0, forward=False))
        b = min(hi, to_quiet(rms, v1, forward=True))
        # невпевнено вирівняний сусід насправді звучить усередині шматка: «коли [ти заганяєшся], заганяєш» —
        # справжнє «ти» тут, а не там, куди його поставило вирівнювання. Слово лишаємо, ріжемо після (до) нього
        if gw and not reliable(a_) and _norm(gw[0][0]) == _norm(a_["w"]):
            a = max(a, to_quiet(rms, v0 + max(0.0, gw[0][2]), forward=True))
        if gw and not reliable(b_) and _norm(gw[-1][0]) == _norm(b_["w"]):
            b = min(b, to_quiet(rms, v0 + max(0.0, gw[-1][1]), forward=False))
        if b - a < 0.08:
            continue
        out.append([round(a, 3), round(b, 3)])
        print(f"  між «{a_['w']}» і «{b_['w']}» чути «{text}» — вирізаю {a:.2f}–{b:.2f} с")
    return out


if __name__ == "__main__":
    name = sys.argv[1]
    have = {tuple(c) for c in json.loads((WORK / f"{name}.edl.json").read_text()).get("cut_times", [])}
    new = (fixes(name) if "--no-verify" not in sys.argv and (WORK / f"{name}.verify.json").exists() else []) \
        + gap_fixes(name)
    new = [c for c in new if tuple(c) not in have]
    if not new:
        sys.exit(1)
    edl_path = WORK / f"{name}.edl.json"
    edl = json.loads(edl_path.read_text())
    edl["cut_times"] = sorted(edl.get("cut_times", []) + new)
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=1))
    sys.exit(0)
