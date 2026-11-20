"""Склейка майстер-файлу за монтажним листом.

EDL (work/<name>.edl.json):
{
  "keep": [[from_word, to_word], ...],       # індекси слів з words.txt, включно
  "word_fixes": {"71": "шортовую"},             # помилки Whisper, тільки для субтитрів
  "broll": [{"at_word": 57, "clip": "file.mp4", "dur": 2.5, "clip_start": 0}, ...],
  "cut_times": [[364.90, 365.84]],            # вирізати за часом сирого відео (фальстарти, які Whisper злив у слово)
  "notes": "..."
}

Паузи між фразами скорочуються до PAUSE (за замовчуванням 0,5 с), коротші лишаються як є.
Точки різу вирівнюються на кадри, щоб звук і відео не розʼїжджались.

Використання: python cut.py work/<name>.edl.json
Результат: work/<name>.master.mp4, work/<name>.cut.json (таймлайн + слова в новому часі)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from config import FFMPEG, FFPROBE, WORK, out_fps as pick_fps

PAD_IN = 0.06       # запас перед першим словом шматка
PAD_OUT = 0.10      # запас після останнього слова
PAUSE = 0.4         # стандартна пауза між фразами, с (монтажер: «якщо умови звичайні — 0,5»; у його 4.1 виміряно ≤0,42)
MIN_PIECE = 0.12
OUT_FPS = 30
FADE = 0.012        # мікрофейд звуку на стиках від клацань


def probe_fps(video: str) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", video],
                       capture_output=True, text=True, check=True)
    # для відео з метаданими повороту ffprobe дописує зайву кому: «30000/1001,»
    n, d = r.stdout.strip().split(",")[0].split("/")
    return int(n) / int(d)


def load_rms(wav: Path):
    """Гучність звуку кадрами по 10 мс (для пошуку тихої точки різу)."""
    import wave
    import numpy as np
    with wave.open(str(wav)) as f:
        sr = f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32)
    hop = sr // 100
    n = len(x) // hop
    return np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1)), 0.01


def stray_syllable(rms, word: dict, min_gap: int = 3, floor: float = 0.0, min_burst: int = 1) -> tuple[float, float] | None:
    """Зайвий склад, який Whisper приклеїв до початку слова: «І тоді» → «Тоді», «калорій. І… але» → «Але».
    Якщо на початку слова є короткий звук ≤0,3 с, відділений тишею ≥min_gap×10 мс від решти слова, повертає
    (початок цього звуку, точку різу в тиші після нього). floor — раніше цього часу не заходимо (кінець попереднього
    слова). Для кінців слів не застосовуємо: пауза перед останнім складом («реєстр-уйтесь») — звичайна змичка
    приголосної, і правило зрізало б склад."""
    import numpy as np
    r, step = rms
    a, b = int(word["start"] / step), int(word["end"] / step)
    if b - a < 8:
        return None
    seg = np.convolve(r[a:b], np.ones(3) / 3, mode="same")  # згладжування, щоб поодинокі сплески не рвали паузу
    peak = float(np.percentile(seg, 90))
    loud, quiet = seg > 0.3 * peak, seg < 0.12 * peak
    if not loud.any():
        return None
    on = int(np.argmax(loud))
    i = on
    while i < len(seg) and not quiet[i]:
        i += 1
    j = i
    while j < len(seg) and quiet[j]:
        j += 1
    # звук міг початися ще до межі слова, яку поставив Whisper, — ведемо початок назад до тиші, але не далі floor
    k, lo = a + on, int(floor / step) + 1
    while k > lo and r[k - 1] >= 0.12 * peak:
        k -= 1
    if not (min_burst <= a + i - k <= 35 and j - i >= min_gap and j < len(seg) and loud[j:].sum() >= 5):
        return None
    return k * step, (a + (i + j) // 2) * step


FILLERS = {"і", "й", "а", "е", "ее", "еее", "м", "мм", "ммм", "м-м", "м-м-м", "хм", "ем", "ну", "и", "э"}


def is_filler(wav: Path, t0: float, t1: float, _m={}) -> bool:
    """Розпізнає вирізаний шматок окремо: заповнювач («і», «м-м», «хм») — так; слово чи шум (Whisper на шумі
    «бачить» «Дякую за перегляд») — ні. Без цієї перевірки правило різало б початок справжніх слів («с-трах»)."""
    import re
    import subprocess as sp
    import tempfile
    # кеш на диску: повторна склейка того ж відео не вантажить Whisper (без кешу склейка 46 → 137 с)
    cache_file = wav.with_suffix(".fillers.json")
    key = f"{t0:.2f}-{t1:.2f}"
    if "cache" not in _m or _m.get("cache_file") != cache_file:
        _m["cache"] = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        _m["cache_file"] = cache_file
    if key in _m["cache"]:
        return _m["cache"][key]
    from faster_whisper import WhisperModel
    from config import WHISPER_DIR, WHISPER_MODEL
    if "m" not in _m:
        _m["m"] = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR))
    from config import tmpwav
    with tmpwav() as f:
        sp.run([FFMPEG, "-loglevel", "error", "-y", "-ss", f"{max(0, t0 - 0.03):.3f}", "-to", f"{t1:.3f}", "-i", str(wav),
                "-af", "adelay=300,apad=pad_dur=0.6", f.name], check=True)
        segs, _ = _m["m"].transcribe(f.name, language=os.environ.get("MONTAGE_LANG", "uk"), condition_on_previous_text=False)
        text = re.sub(r"[^\w-]", " ", " ".join(x.text for x in segs).lower()).split()
    _m["cache"][key] = len(text) == 1 and text[0] in FILLERS
    cache_file.write_text(json.dumps(_m["cache"]))
    return _m["cache"][key]


def quietest_between(rms, a: float, b: float) -> float:
    """Найтихіший кадр (10 мс) у проміжку [a, b]."""
    import numpy as np
    r, step = rms
    i0, i1 = int(a / step), max(int(a / step) + 1, int(b / step))
    return (i0 + int(np.argmin(r[i0:i1]))) * step


def snap_to_silence(rms, t: float, lo: float, hi: float, forward: bool) -> float:
    """Від точної межі слова (вирівнювання) ідемо до тиші: вперед — щоб не обрізати хвіст («жир-р»),
    назад — щоб не обрізати приступ («т-оді»). Далі за lo/hi (сусіднє слово) не заходимо."""
    import numpy as np
    r, step = rms
    quiet = 0.08 * float(np.percentile(r, 90))
    i = int(t / step)
    lim = int((hi if forward else lo) / step)
    while (i < lim if forward else i > lim) and 0 <= i < len(r) and r[i] > quiet:
        i += 1 if forward else -1
    return i * step


def build_pieces(words, keep, silences, fps, pause=PAUSE, rms=None, wav=None, cut_times=(), aligned=False):
    ranges = []
    for a, b in keep:
        if aligned and rms is not None:
            # точні межі (align.py): ріжемо в тиші біля слова, не заходячи в сусідні слова — вигук «і» поруч
            # уже окреме слово, яке «мозок» виключив із keep
            # сусід із невпевненим вирівнюванням (a < 0,6) — найменш обмежувальна межа з двох: «Це» (0,47)
            # вирівнялось на хвіст «реєструйтесь» і склейка обрізала «-сь»
            def bound(w, end):
                if "whisper" not in w or w.get("a", 0) >= 0.6:
                    return w["end"] if end else w["start"]
                return min(w["end"], w["whisper"][1]) if end else max(w["start"], w["whisper"][0])
            lo = bound(words[a - 1], True) + 0.02 if a > 0 else 0.0
            hi = bound(words[b + 1], False) - 0.02 if b + 1 < len(words) else words[b]["end"] + 1.0
            t0 = max(lo, snap_to_silence(rms, words[a]["start"], lo, words[a]["end"], forward=False) - PAD_IN)
            t1 = min(hi, snap_to_silence(rms, words[b]["end"], words[b]["start"], hi, forward=True) + PAD_OUT)
            # тиші між словами немає (розтягнуте «і…» впритул до «завжди»): межа сусіднього слова від вирівнювання
            # тут неточна (20 мс на протяжне «і»), і різ по ній лишав хвіст вигуку — беремо найтихішу точку проміжку
            if t0 <= lo + 1e-3 and words[a]["start"] - lo > 0.05:
                t0 = quietest_between(rms, lo, words[a]["start"])
            if t1 >= hi - 1e-3 and hi - words[b]["end"] > 0.05:
                t1 = quietest_between(rms, words[b]["end"], hi)
            # вирівнювання буває зсуває кінець останнього слова на 0,3–0,4 с раніше, а тиша між складами зупиняє
            # snap — хук 115 обривався на «запла-»: кінець куска не раніше кінця слова за Whisper
            if "whisper" in words[b] and words[b]["whisper"][1] > t1 + 0.05:
                t1 = min(hi, words[b]["whisper"][1] + 0.05)
            ranges.append([max(0.0, t0), t1])
            continue
        t0 = words[a]["start"] - PAD_IN
        t1 = words[b]["end"] + PAD_OUT
        if a > 0:
            t0 = max(t0, words[a - 1]["end"])
        if rms is not None:  # «І тоді» з «І» всередині слова «Тоді»: починаємо після «і»
            st = stray_syllable(rms, words[a])
            t0 = st[1] if st and (wav is None or is_filler(wav, *st)) else t0
        if b + 1 < len(words):
            t1 = min(t1, words[b + 1]["start"])
        # усередині фрази — тільки з довгою паузою після складу (≥150 мс), щоб не прийняти змичку приголосної за склад
        cuts = [st for k in range(a + 1, b + 1)
                if rms is not None and wav is not None
                and (st := stray_syllable(rms, words[k], min_gap=15, floor=words[k - 1]["end"], min_burst=15))
                and is_filler(wav, *st)]
        cur = max(0.0, t0)
        for s0, s1 in cuts:
            if s0 - 0.02 > cur:
                ranges.append([cur, s0 - 0.02])
            cur = max(cur, s1)
        ranges.append([cur, t1])
    # ручні вирізки за часом (фальстарти всередині слова Whisper: «а потім… потім зрив» → одне слово «зрив»)
    for c0, c1 in cut_times:
        nxt = []
        for r0, r1 in ranges:
            if c1 <= r0 or c0 >= r1:
                nxt.append([r0, r1])
                continue
            if c0 - r0 >= MIN_PIECE:
                nxt.append([r0, c0])
            if r1 - c1 >= MIN_PIECE:
                nxt.append([c1, r1])
        ranges = nxt

    # тихий кінець слова («запла-кала», «фо-то») детектор тиші бере за паузу і ріже по ній — хук 115 обривався
    # на півслові: пауза не може починатися всередині збереженого слова (межі Whisper, не далі 0,8 с)
    prot = [w["whisper"] if "whisper" in w else (w["start"], w["end"]) for a, b in keep for w in words[a:b + 1]]

    def silence_start(s):
        for ws, we in prot:
            if s < we <= s + 0.8 and ws < s + 0.8:  # пауза зачіпає слово — починається після нього
                s = we
        return s

    pieces = []
    for t0, t1 in ranges:
        cur = t0
        for s, e in silences:
            s = silence_start(s)
            if e - s < pause or e <= t0 or s >= t1:
                continue
            cut_a, cut_b = max(s + pause / 2, t0), min(e - pause / 2, t1)
            if cut_b - cut_a <= 0:
                continue
            if cut_a - cur >= MIN_PIECE:
                pieces.append([cur, cut_a])
            cur = cut_b
        if t1 - cur >= MIN_PIECE:
            pieces.append([cur, t1])

    snap = lambda t: round(t * fps) / fps
    merged = []
    for s, e in ((snap(s), snap(e)) for s, e in pieces):
        if merged and s - merged[-1][1] < 1.5 / fps:
            merged[-1][1] = max(merged[-1][1], e)
        elif e - s >= MIN_PIECE:
            merged.append([s, e])
    return merged


def remap_words(words, pieces, kept):
    """Переносить слова на новий таймлайн.

    Whisper іноді ставить слово на паузу, яку ми вирізаємо. Таке слово (якщо воно збережене
    в keep) не викидаємо, а притискаємо до найближчого шматка — інакше воно зникне із субтитрів
    і до нього не можна буде прив'язати перебивку чи накладку.
    """
    timeline, dst = [], 0.0
    for s, e in pieces:
        timeline.append({"src_start": s, "src_end": e, "dst_start": round(dst, 3)})
        dst += e - s

    out = []
    for w in words:
        if w["i"] not in kept:
            continue
        mid = (w["start"] + w["end"]) / 2
        # шматок, що містить середину слова, або найближчий за відстанню
        tl = min(timeline, key=lambda p: 0 if p["src_start"] <= mid < p["src_end"]
                 else min(abs(mid - p["src_start"]), abs(mid - p["src_end"])))
        s, e = tl["src_start"], tl["src_end"]
        a = min(max(w["start"], s), e - 0.12)
        b = max(a + 0.12, min(max(w["end"], s), e))
        out.append({**w, "start": round(tl["dst_start"] + a - s, 3),
                    "end": round(tl["dst_start"] + b - s, 3)})
    out.sort(key=lambda w: (w["start"], w["i"]))
    return out, timeline, dst


TARGET_SYL = 6.2         # складів/с після прискорення: стільки тримав монтажер у 4.1 (3,05 слова/с ≈ 6,3 склада/с)
SPEED_LO, SPEED_HI = 1.0, 1.30   # 1,35 ковтало склади («вибухала» → «б бухала»); людський 4.1 ≈ ×1,27
STEP = 0.15
VOWELS = set("аеєиіїоуюяaeiouыэё")


def piece_speeds(pieces: list, words: list) -> list[float]:
    """Прискорення для кожного шматка: повільні — сильніше, швидкі — слабше або ніяк, щоб уся мова звучала
    близько TARGET_SYL. Однакові ×1,25 робили з 7-складових секунд («починає бунтувати») 8,75 — склади ковтались.
    Короткі шматки (<2 с) рахуємо разом із сусідами: інакше одне слово дає випадкову швидкість."""
    syl, dur = [], []
    for s0, s1 in pieces:
        ws = [w for w in words if s0 - 0.05 <= (w["start"] + w["end"]) / 2 <= s1 + 0.05]
        syl.append(sum(sum(ch in VOWELS for ch in w["w"].lower()) for w in ws))
        dur.append(max(1e-3, s1 - s0))
    out = []
    for k in range(len(pieces)):
        lo, hi = k, k
        # сусідів додаємо лише коли складів замало для надійного темпу (не за тривалістю: інакше швидке
        # «починає бунтувати» усереднюється з повільними сусідами й прискорюється далі)
        while sum(syl[lo:hi + 1]) < 6 and (lo > 0 or hi < len(pieces) - 1):
            lo, hi = max(0, lo - 1), min(len(pieces) - 1, hi + 1)
        rate = sum(syl[lo:hi + 1]) / sum(dur[lo:hi + 1])
        out.append(min(SPEED_HI, max(SPEED_LO, TARGET_SYL / rate if rate else 1.0)))
    # сусідні фрази — не різкіше ніж на STEP: перепад ×1,00 → ×1,35 чутно як «прискорилась посеред думки»
    for _ in range(3):
        for k in range(1, len(out)):
            out[k] = min(max(out[k], out[k - 1] - STEP), out[k - 1] + STEP)
        for k in range(len(out) - 2, -1, -1):
            out[k] = min(max(out[k], out[k + 1] - STEP), out[k + 1] + STEP)
    return [round(v, 3) for v in out]


def split_for_tempo(pieces: list, words: list, fps: float, min_len: float = 1.5, gap: float = 0.12) -> list:
    """Довгий шматок (одна безперервна ділянка сирого відео) ділимо на фрази по паузах між словами, щоб кожна
    фраза мала свій темп. Межі — посередині паузи, тож зміна швидкості не чутна; кадри ті самі (сусідні ділянки)."""
    snap = lambda t: round(t * fps) / fps
    out = []
    for s0, s1 in pieces:
        ws = sorted((w for w in words if s0 <= (w["start"] + w["end"]) / 2 <= s1), key=lambda w: w["start"])
        cuts = [s0]
        for a, b in zip(ws, ws[1:]):
            mid = snap((a["end"] + b["start"]) / 2)
            if b["start"] - a["end"] >= gap and mid - cuts[-1] >= min_len and s1 - mid >= min_len:
                cuts.append(mid)
        cuts.append(s1)
        out += [[a, b] for a, b in zip(cuts, cuts[1:])]
    return out


def render_master(src, pieces, dst, src_fps, out_fps, speed=1.0):
    """Майстер зі шматків. Кожен шматок — окремий вхід із пошуком (-ss/-t): ffmpeg декодує лише потрібні
    секунди, а не все сире відео (приклад: 70 с замість 500 с, склейка 46 → ~15 с). Кадри ті самі."""
    n = len(pieces)
    speeds = speed if isinstance(speed, list) else [speed] * n
    inputs, chain = [], []
    for i, (s, e) in enumerate(pieces):
        d, v = e - s, speeds[i]
        inputs += ["-ss", f"{s:.4f}", "-t", f"{d:.4f}", "-i", src]
        # прискорення кожного шматка своє: відео — розтяг часу, звук — atempo (без зміни висоти голосу)
        # 23.10: iPhone-вихідники — 60p-контейнер із нерівними дублями (реально ~30p): без mpdecimate fps=30 місцями
        # бере дубль кожен 3-й кадр → «підвисання» (~20 fps). Прибираємо дублі, fps нижче рівно заповнює час.
        dedup = "mpdecimate=hi=64*2:lo=64:frac=0.1," if os.environ.get("MONTAGE_DEDUP", "1") == "1" else ""
        chain.append(f"[{i}:v]{dedup}setpts=(PTS-STARTPTS)/{v}" + (f",fps={out_fps}" if dedup else "") + f"[v{i}]")
        chain.append(f"[{i}:a]asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={FADE},afade=t=out:st={max(0, d - FADE):.4f}:d={FADE}"
                     + (f",atempo={v}" if v != 1.0 else "") + f"[a{i}]")
    chain.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    # рівна частота кадрів після різних прискорень; 50/60 к/с зі смартфона — у 25/30
    chain.append(f"[vc]fps={out_fps}[vout]")
    chain.append("[ac]anull[aout]")

    script = WORK / f"_cut_filter_{Path(dst).stem}.txt"  # своє ім'я: паралельні склейки не перезаписують одна одну (22.10)
    script.write_text(";".join(chain))
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", *inputs,
                    "-/filter_complex", str(script), "-map", "[vout]", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                    "-c:a", "aac", "-b:a", "192k", str(dst)], check=True)


if __name__ == "__main__":
    # python cut.py work/<name>.edl.json [speed] [pause] — speed 1.1 = мова на 10% швидше,
    # pause = до скількох секунд скорочуємо паузи між фразами
    speed_arg = sys.argv[2] if len(sys.argv) > 2 else "1.0"  # число або auto (своє прискорення для кожного шматка)
    pause = float(sys.argv[3]) if len(sys.argv) > 3 else PAUSE
    edl_path = Path(sys.argv[1])
    name = edl_path.name.removesuffix(".edl.json")
    edl = json.loads(edl_path.read_text())
    tr = json.loads((WORK / f"{name}.transcript.json").read_text())
    silences = json.loads((WORK / f"{name}.silence.json").read_text())
    words = [w for s in tr["segments"] for w in s["words"]]
    for i, w in enumerate(words):
        w["i"] = i
    # виправлення помилок розпізнавання для субтитрів: {"індекс слова": "правильний текст"}
    for i, text in edl.get("word_fixes", {}).items():
        words[int(i)]["w"] = text
    for i in edl.get("emphasis", []):  # слова, які в субтитрах роблять більшими
        words[i]["emph"] = True

    fps = probe_fps(tr["source"])
    wav = WORK / f"{name}.wav"
    aligned = bool(tr.get("aligned"))  # точні межі + дослівна розшифровка: старі евристики «і» не потрібні
    pieces = build_pieces(words, edl["keep"], silences, fps, pause,
                          *((load_rms(wav), None if aligned else wav) if wav.exists() else (None, None)),
                          cut_times=edl.get("cut_times", []), aligned=aligned)
    if edl.get("lead_in") and pieces:  # 23.10: почати раніше першого слова (дія в кадрі до мови: спікер робить дію, 48.1 h3)
        pieces[0] = [max(0.0, pieces[0][0] - float(edl["lead_in"])), pieces[0][1]]
    kept = {i for a, b in edl["keep"] for i in range(a, b + 1)}
    if speed_arg == "auto":  # темп по фразах: довгі шматки ділимо на фрази (лише для темпу, кадри ті самі)
        pieces = split_for_tempo(pieces, [words[i] for i in sorted(kept)], fps)
    new_words, timeline, total = remap_words(words, pieces, kept)
    timing = [w for w in words]  # для темпу — межі Whisper (на них калібровано), не щільні межі вирівнювання
    timing = [{**w, "start": w["whisper"][0], "end": w["whisper"][1]} if "whisper" in w else w for w in timing]
    speeds = piece_speeds(pieces, timing) if speed_arg == "auto" else [float(speed_arg)] * len(pieces)
    # MONTAGE_SPEED_MULT: «ускорь ещё на 20 %» поверх авто-темпу (×1.2 до кожного шматка)
    mult = float(os.environ.get("MONTAGE_SPEED_MULT", "1"))
    if mult != 1:
        speeds = [round(v * mult, 3) for v in speeds]
    # таймлайн стискається по шматках: кожен своїм прискоренням
    starts1 = [t["dst_start"] for t in timeline]
    durs = [e - s for s, e in pieces]
    newstart, acc = [], 0.0
    for d, v in zip(durs, speeds):
        newstart.append(acc)
        acc += d / v

    def to_new(t: float) -> float:
        k = max(0, max((i for i, s0 in enumerate(starts1) if s0 <= t + 1e-6), default=0))
        return round(newstart[k] + (t - starts1[k]) / speeds[k], 3)

    for w in new_words:
        w["start"], w["end"] = to_new(w["start"]), to_new(w["end"])
    for t, ns, v in zip(timeline, newstart, speeds):
        t["dst_start"], t["speed"] = round(ns, 3), v
    total = acc
    speed = round(sum(durs) / total, 3)  # середнє — для логів і cut.json

    by_idx = {w["i"]: w for w in new_words}
    broll = []
    for b in edl.get("broll", []):
        w = by_idx.get(b["at_word"])
        if w is None:
            print(f"! перебивка {b['clip']}: слово {b['at_word']} вирізане, пропускаю")
            continue
        dur = b.get("dur", 2.5)
        if b.get("to_word") in by_idx:  # перебивка тримається на всю фразу
            dur = max(0.8, by_idx[b["to_word"]]["end"] - w["start"] + 0.05)
        dur = min(dur, b.get("max_dur", 9.0), 9.0, total - w["start"])
        broll.append({**b, "start": w["start"], "dur": round(dur, 2)})
    broll.sort(key=lambda b: b["start"])
    for cur, nxt in zip(broll, broll[1:]):  # сусідні кадри однієї фрази не накладаються
        if cur["start"] + cur["dur"] > nxt["start"]:
            cur["dur"] = round(max(0.5, nxt["start"] - cur["start"]), 2)

    # графічні накладки (overlays.py): прив'язка до слів → час у новому таймлайні
    overlays = []
    for o in edl.get("overlays", []):
        w0 = by_idx.get(o["from_word"])
        w1 = by_idx.get(o.get("to_word")) if o.get("to_word") is not None else None
        if w0 is None:
            print(f"! накладка {o['type']}: слово {o['from_word']} вирізане, пропускаю")
            continue
        item = {**o, "start": w0["start"], "end": (w1["end"] + 0.1) if w1 else None}
        if o.get("broll_clip"):
            wb = by_idx.get(o.get("broll_at_word"))
            item["broll_start"] = wb["start"] if wb else w0["start"] + 1.0
        overlays.append(item)

    master = WORK / f"{name}.master.mp4"
    out_fps = pick_fps(fps)
    render_master(tr["source"], pieces, master, fps, out_fps, speeds)
    if speed_arg == "auto":
        print("прискорення по шматках: " + " ".join(f"×{v:.2f}" for v in speeds) + f" (середнє ×{speed:.2f})")
    (WORK / f"{name}.cut.json").write_text(json.dumps(
        {"master": str(master), "fps": out_fps, "speed": speed, "duration": round(total, 3),
         "timeline": timeline, "words": new_words, "broll": broll,
         "overlays": [{**o, "end": o["end"] if o["end"] is not None else round(total, 3)} for o in overlays]},
        ensure_ascii=False, indent=1))
    print(f"шматків: {len(pieces)}, тривалість: {tr['duration']:.1f}s → {total:.1f}s → {master}")
