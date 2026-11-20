"""Міст «агент → Remotion»: перетворює результат склейки (cut.json) на props для шаблону Remotion.

Нарізка, звук, трекінг обличчя лишаються в Python; Remotion малює лише візуальний шар
(кадрування з плавним зумом, перебивки з переходами, субтитри, плашка-хук, картка Instagram, стрілки).

Використання:
  python to_remotion.py приклад --fmt 9x16 --style box \\
      --hook-src input/raw/<файл>.mp4 --hook-in 69.05 --hook-out 71.25 \\
      --hook-title "Що ти зрозуміла, коли схудла на 80 кілограмів?"
Результат: remotion/public/<name>/… (посилання на файли) і remotion/props/<name>_<fmt>.json
"""
import argparse
import json
import re
import math
import os
import subprocess
from pathlib import Path

from audio import pick_music, render_audio
from config import DATA, FFMPEG, FFPROBE, INPUT_BROLL, NPX, PY, ROOT, VENC, WORK
from overlays import is_portrait
from render import FORMATS, STYLES, clean, crop_box, crop_path, group_words, merge_tokens, probe_size

RM = ROOT / "remotion"


def duration(path: Path) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout)


def link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    # жорстке посилання: збирач Remotion не віддає символьні посилання з public/, а копіювати великі файли довго
    try:
        os.link(src.resolve(), dst)
    except OSError:
        import shutil
        shutil.copy2(src, dst)


def render_rm(composition: str, props: Path, out: Path, scale: float = 1.0) -> None:
    """Рендер у Remotion з вимогами монтажера: H.264, Rec.709, ≤10 Мбіт/с.
    scale < 1 — чернетка для перевірки (0.5 = 540×960, ~4× менше пікселів); фінал завжди 1.0."""
    extra = [f"--scale={scale}", "--video-bitrate=3M"] if scale < 1 else ["--video-bitrate=8M"]
    # під великим навантаженням машини декодер кадрів не встигає за 30 с (delayRender timeout) — довший тайм-аут
    # (MONTAGE_RM_TIMEOUT, мс) і один повтор рендеру
    extra += [f"--timeout={os.environ['MONTAGE_RM_TIMEOUT']}"] if os.environ.get("MONTAGE_RM_TIMEOUT") else []
    cmd = [NPX, "remotion", "render", "src/index.ts", composition, str(out.resolve()),
           f"--props={props.resolve()}", "--codec=h264", "--color-space=bt709", *extra,
           "--log=error", *([f"--concurrency={os.environ['MONTAGE_CONCURRENCY']}"] if os.environ.get("MONTAGE_CONCURRENCY") else [])]
    for attempt in range(3):
        if subprocess.run(cmd, cwd=RM).returncode == 0:
            return
        print(f"  рендер не вдався — повтор {attempt + 1}", flush=True)
    subprocess.run(cmd, cwd=RM, check=True)


def media_size(path: Path) -> tuple[int, int]:
    """Ширина й висота з урахуванням повороту в метаданих."""
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_side_data=rotation", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    st = json.loads(r.stdout)["streams"][0]
    w, h = st["width"], st["height"]
    if any(abs(int(d.get("rotation", 0))) in (90, 270) for d in st.get("side_data_list", [])):
        w, h = h, w
    return w, h


def reframe(items: list) -> list:
    """Аналіз горизонтальних перебивок (reframe.py, окремий процес — cv2)."""
    if not items:
        return []
    inp, out = WORK / "_reframe_in.json", WORK / "_reframe_out.json"
    inp.write_text(json.dumps(items))
    subprocess.run([PY, str(ROOT / "reframe.py"), str(inp), str(out)], check=True,
                   cwd=ROOT, stderr=subprocess.DEVNULL)
    return json.loads(out.read_text())


def crop_master(master: Path, name: str, fmt: str, path: list, cw: int, ch: int, W: int, H: int, grade: str = "null"):
    """Майстер, обрізаний до смуги, де ходить кадр цього формату (усі точки шляху + розмір кадру).
    Remotion декодує кожен кадр майстра повністю — для 2560×1440 і кадру ~810 px це втричі зайвих пікселів.
    Пікселі в кадрі ті самі (без масштабування). Повертає (файл, x0, y0, ширина, висота)."""
    x0 = max(0, min(int(x) for _, x, _ in path)) // 2 * 2
    y0 = max(0, min(int(y) for _, _, y in path)) // 2 * 2
    x1 = min(W, max(int(x) for _, x, _ in path) + cw + 2)
    y1 = min(H, max(int(y) for _, _, y in path) + ch + 2)
    w, h = (x1 - x0 + 1) // 2 * 2, (y1 - y0 + 1) // 2 * 2
    w, h = min(w, W - x0), min(h, H - y0)
    if w * h > 0.8 * W * H:  # майже весь кадр — не обрізаємо (але кольорокор, якщо є, все одно накладаємо)
        if grade == "null":
            return master, 0, 0, W, H
        x0, y0, w, h = 0, 0, W // 2 * 2, H // 2 * 2
    out = WORK / f"{name}_rm_master_{fmt}.mp4"
    key = WORK / f"{name}_rm_master_{fmt}.key"
    stamp = f"{master.stat().st_mtime}|{x0},{y0},{w},{h}|{grade}"
    if not (out.exists() and key.exists() and key.read_text() == stamp):
        subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(master), "-an", "-vf", f"crop={w}:{h}:{x0}:{y0},{grade}",
                        "-c:v", VENC, "-b:v", "24M", str(out)], check=True)
        key.write_text(stamp)
    return out, x0, y0, w, h


def blurred_bg(src: Path, kind: str, ow: int, oh: int) -> Path:
    """Готовий розмитий фон для горизонтальної перебивки — те саме, що CSS `blur(40px) brightness(0.65)
    scale(1.25)` у шаблоні, але один раз, а не в кожному кадрі (найважча операція рендеру). Чверть роздільності:
    після розмиття на 40 px деталей там немає, Remotion розтягує до повного кадру."""
    bw, bh = ow // 4 // 2 * 2, oh // 4 // 2 * 2
    # cover на (ow,oh) → розмиття σ=40 → наїзд 1.25 від центру; у чверті роздільності σ=10
    vf = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},gblur=sigma=10,"
          f"crop={int(bw / 1.25) // 2 * 2}:{int(bh / 1.25) // 2 * 2},scale={bw}:{bh},"
          f"format=rgb24,colorchannelmixer=rr=0.65:gg=0.65:bb=0.65")
    out = WORK / f"_bg_{fmt_tag(ow, oh)}_{src.stem}{'.jpg' if kind == 'photo' else '.mp4'}"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    if kind == "photo":
        subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(src), "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out)],
                       check=True)
    else:
        subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(src), "-an", "-vf", vf + ",format=yuv420p",
                        "-c:v", VENC, "-b:v", "1500k", str(out)], check=True)
    return out


def fmt_tag(ow: int, oh: int) -> str:
    return f"{ow}x{oh}"


def build_master(name: str, cut: dict, a) -> tuple[Path, float]:
    """Майстер для Remotion: [хук-питання] + тіло. Перешифровка апаратна (VideoToolbox) — швидко."""
    master = Path(cut["master"])
    if not a.hook_src:
        return master, 0.0
    W, H = probe_size(str(master))
    fps = cut["fps"]
    hook = WORK / f"{name}_rm_hook.mp4"
    out = WORK / f"{name}_rm_master.mp4"
    # кеш: той самий хук і той самий майстер — не перезбираємо для кожного формату
    stamp = WORK / f"{name}_rm_master.key"
    key = f"{a.hook_src}|{a.hook_in}|{a.hook_out}|{master.stat().st_mtime}"
    if out.exists() and hook.exists() and stamp.exists() and stamp.read_text() == key:
        return out, duration(hook)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-ss", str(a.hook_in), "-to", str(a.hook_out), "-i", a.hook_src,
                    "-vf", f"scale={W}:{H},fps={fps}", "-c:v", VENC, "-b:v", "24M",
                    "-c:a", "aac", "-ar", "48000", str(hook)], check=True)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(hook), "-i", str(master), "-filter_complex",
                    "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
                    "-c:v", VENC, "-b:v", "24M", "-c:a", "aac", "-ar", "48000", str(out)], check=True)
    stamp.write_text(key)
    return out, duration(hook)


STOCK_DIR = Path(os.environ["MONTAGE_STOCK_DIR"]).resolve() if os.environ.get("MONTAGE_STOCK_DIR") else ROOT / "input" / "stock_vit"


def build_vhook(a, words: list, off: float, total: float, pub: Path, rid: str) -> dict:
    """Візуальний хук на першу фразу (стиль vit, відгук замовника 15.10): split — верх стокове відео, низ аватар;
    text — великий кінетичний текст хука + punch-in зум. Межа хука — кінець першого речення."""
    import re
    mw = merge_tokens(words)
    k = next((i for i, w in enumerate(mw) if re.search(r"[.!?…][»\"')]*$", w["w"].strip())), min(len(mw) - 1, 11))
    nxt = mw[k + 1]["start"] if k + 1 < len(mw) else total
    end = a.vhook_end + off if a.vhook_end else min(nxt - 0.04, mw[k]["end"] + 0.3)
    hw = [w for w in mw if w["start"] < end - 0.05] if a.vhook_end else mw[:k + 1]
    # ключові слова (жовтий акцент): виділені «мозком», інакше — найдовше слово; не більше двох
    want = [x.strip().upper() for x in (a.vhook_keys or "").split(",") if x.strip()]
    keys = [i for i, w in enumerate(hw) if clean(w["w"]).upper() in want][:2] if want else \
        [i for i, w in enumerate(hw) if w.get("emph")][-2:]
    rest = sorted((i for i in range(len(hw)) if i not in keys and len(clean(hw[i]["w"])) >= 5), key=lambda i: -len(clean(hw[i]["w"])))
    keys = sorted(keys + rest[:2 - len(keys)]) if len(keys) < 2 else keys  # завжди 2 жовті акценти (замовник 15.10)
    # сторінки по 2–4 рядки великого тексту (≈ 16 знаків: кегль ≈2× звичайних сабів): ріжемо по комах/тире, прийменник не висить у кінці сторінки
    items = [{"t": clean(w["w"]), "start": round(max(off, w["start"]), 3), "key": i in keys} for i, w in enumerate(hw)]
    punct = [bool(re.search(r"[,.!?;:—–-]$", w["w"].strip())) for w in hw]
    def page_cost(i, j):  # сторінка items[i:j]
        n = sum(len(x["t"]) + 1 for x in items[i:j])
        c = (n - 19) ** 2 + (10_000 if n > 26 and j - i > 1 else 0)
        if j < len(items):
            c += 120 if len(items[j - 1]["t"]) <= 2 else 0
            c -= 90 if punct[j - 1] or items[j]["t"] in ("—", "–") else 0
        return c
    best, prev = [0.0] + [float("inf")] * len(items), [0] * (len(items) + 1)
    for j in range(1, len(items) + 1):
        for i in range(max(0, j - 7), j):
            c = best[i] + page_cost(i, j)
            if c < best[j]:
                best[j], prev[j] = c, i
    cuts, j = [], len(items)
    while j > 0:
        cuts.append((prev[j], j)); j = prev[j]
    pages = [items[i:j] for i, j in reversed(cuts)]
    pages = [{"start": pg[0]["start"] if j else off, "end": pages[j + 1][0]["start"] if j + 1 < len(pages) else end, "words": pg}
             for j, pg in enumerate(pages)]
    # стоки: явно (--vhook-stock) або з каталогу input/stock_vit за полем "for" (стем ролика)
    cat = json.loads((STOCK_DIR / "catalog.json").read_text()) if (STOCK_DIR / "catalog.json").exists() else []
    files = [x for x in (a.vhook_stock or "").split(",") if x] or \
            [c["file"] for c in cat if any(a.name == f or a.name.rstrip("v") == f for f in c.get("for", []))]
    if a.vhook == "split" and not files:
        raise SystemExit("✗ --vhook split: немає стокових кліпів (--vhook-stock або catalog.json → for)")
    hd = end - off
    files = files[:2] if hd >= 2.4 else files[:1]
    clips = []
    for j, f in enumerate(files):
        link(STOCK_DIR / f, pub / "stock" / f)
        seg = hd / len(files)
        clips.append({"file": f"{rid}/stock/{f}", "start": round(off + j * seg, 3), "dur": round(seg + (0.04 if j + 1 < len(files) else 0), 3),
                      "clipStart": 0.3})
    return {"mode": a.vhook, "start": off, "end": round(end, 3), "split": 0.5 if a.fmt == "9x16" else 0.46,
            "keyAt": hw[keys[-1]]["start"], "clips": clips, "pages": pages}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--fmt", default="9x16", choices=FORMATS)
    ap.add_argument("--style", default="box", choices=["box", "pyshka", "vit"])
    ap.add_argument("--hook-src")
    ap.add_argument("--hook-in", type=float, default=0)
    ap.add_argument("--hook-out", type=float, default=0)
    ap.add_argument("--hook-title", default=None)
    ap.add_argument("--box-color", default="#325C3C", help="колір плашки субтитрів (під палітру ролика)")
    ap.add_argument("--render", type=Path, default=None, help="одразу зрендерити у цей файл")
    ap.add_argument("--music", default=None, help="файл музики, назва треку з бібліотеки або auto")
    ap.add_argument("--music-gap", type=float, default=None, help="наскільки тихіше за голос, LU (за замовч. — заміряно для треку)")
    ap.add_argument("--scale", type=float, default=1.0, help="0.5 — швидка чернетка для перевірки")
    ap.add_argument("--master-only", type=Path, default=None,
                    help="лише склейка з хуком (без графіки) у цей файл — перевірити звук і стики за ~1 хв")
    ap.add_argument("--vhook", default="none", choices=["none", "split", "text"],
                    help="візуальний хук на першу фразу (vit): split — сплітом зі стоком, text — великий кінетичний текст + зум")
    ap.add_argument("--vhook-stock", default=None, help="стокові кліпи для хука через кому (input/stock_vit)")
    ap.add_argument("--vhook-keys", default=None, help="1–2 ключові слова хука для жовтого акценту, через кому")
    ap.add_argument("--vhook-end", type=float, default=None, help="кінець хука, с (за замовч. — кінець першого речення)")
    a = ap.parse_args()

    cut = json.loads((WORK / f"{a.name}.cut.json").read_text())
    st = STYLES[a.style]
    ow, oh = FORMATS[a.fmt]
    fps = cut["fps"]
    master, off = build_master(a.name, cut, a)
    # тривалість — за реальним майстром, а не за розрахунком cut.json: після прискорення (atempo/setpts) майстер
    # буває на 0,1–0,2 с довший, і ролик обривав останнє слово («а я повертаюсь до ри…», клієнт)
    total = max(cut["duration"] + off, duration(master))
    if a.master_only:  # 720p, ~4 Мбіт/с: легко відкрити й на телефоні, для перевірки звуку й стиків досить
        subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(master), "-vf", "scale=-2:720",
                        "-c:v", VENC, "-b:v", "4M", "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", str(a.master_only)], check=True)
        print("→", a.master_only)
        raise SystemExit(0)

    # трекінг обличчя на майстрі (окремий процес: cv2 не можна поруч із PyAV); свіжий результат використовуємо повторно
    faces_file = WORK / f"{master.name.removesuffix('.master.mp4')}.faces.json"
    if not faces_file.exists() or faces_file.stat().st_mtime < master.stat().st_mtime:
        subprocess.run([PY, str(ROOT / "track.py"), str(master)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    faces = json.loads(faces_file.read_text())

    # кадрування: та сама логіка, що в render.py (розмір обличчя під стиль, плавний рух, стрибок на стиках)
    W, H = probe_size(str(master))
    cw, ch = crop_box(W, H, ow, oh)
    heights = sorted(f[3] for f in faces if f[1] is not None)
    if st.get("face_h") and heights:
        target_ch = heights[len(heights) // 2] * H / st["face_h"][a.fmt]
        zoom = min(st["max_zoom"], max(1.0, ch / target_ch))
        # MONTAGE_MIN_ZOOM (22.10, спікер): у вихіднику багато простору над головою — мінімальний наїзд, щоб голова була в верхній третині
        zoom = max(zoom, float(os.environ.get("MONTAGE_MIN_ZOOM", "1")))
        cw, ch = int(cw / zoom) // 2 * 2, int(ch / zoom) // 2 * 2
    # справжні стики — лише де щось вирізано; межі фраз для темпу (cut.split_for_tempo) — безперервне відео
    tl = cut["timeline"]
    starts = [0.0] + [p["dst_start"] + off for k, p in enumerate(tl)
                      if k == 0 or p["src_start"] - tl[k - 1]["src_end"] > 0.02]
    path = crop_path(faces, starts, W, H, cw, ch, st.get("face_y", 0.3))
    # адаптивний кольорокор (grade.py, як у FFmpeg-рендері): рахується зі статистики самого відео, накладається
    # разом з обрізкою майстра — окремого проходу немає
    from grade import dim_alpha, grade_filter
    grade = grade_filter(str(master))
    rm_master, cx0, cy0, mW, mH = crop_master(master, a.name, a.fmt, path, cw, ch, W, H, grade)
    print(f"  кольорокор: {grade}")
    # де обличчя реально стоїть у кадрі (частка висоти): кроп не виходить за межі майстра, тож на портретному
    # HeyGen-майстрі обличчя буває нижче за face_y (34.1: 0,43 замість 0,30) — кружечок vit центрується за цим
    _pt = {round(t, 2): y for t, x, y in path}
    _fy = sorted((f[2] * H - _pt.get(round(f[0], 2), cy0)) / ch for f in faces if f[1] is not None)
    face_y_real = round(_fy[len(_fy) // 2], 3) if _fy else st.get("face_y", 0.3)
    path = [(t, x - cx0, y - cy0) for t, x, y in path]

    # субтитри: групи слів тією ж логікою, що й ASS-рендер
    words = [{**w, "start": w["start"] + off, "end": w["end"] + off} for w in cut["words"] if w["w"].strip()]
    groups = []
    for g in group_words(merge_tokens(words), st):
        groups.append({"start": g[0]["start"], "end": g[-1]["end"],
                       "words": [{"t": clean(w["w"]), "emph": bool(w.get("emph"))} for w in g]})
    for g, nxt in zip(groups, groups[1:] + [None]):
        g["end"] = min(g["end"] + 0.25, nxt["start"] if nxt else total)

    # візуальний хук (стиль vit): окремий набір файлів/props на кожен варіант, щоб версії не перезаписували одна одну
    rid = a.name + (f"_v{a.vhook}" if a.vhook != "none" else "")
    pub = RM / "public" / rid
    link(rm_master, pub / f"master_{a.fmt}.mp4")
    vhook = build_vhook(a, words, off, total, pub, rid) if a.vhook != "none" else None
    if vhook:  # під час хука — лише хук: перебивки, що налазять, зсуваємо за його межу (або прибираємо)
        hend, kept_b = vhook["end"] - off, []
        for b in cut["broll"]:
            if b["start"] < hend:
                cut_by = hend - b["start"]
                b = {**b, "start": hend, "dur": b["dur"] - cut_by, "clip_start": b.get("clip_start", 0) + cut_by}
                if b["dur"] < 0.8:
                    continue
            kept_b.append(b)
        cut["broll"] = kept_b
        print(f"  візуальний хук {a.vhook}: 0–{vhook['end']:.2f} с, сторінок тексту {len(vhook['pages'])}, стоків {len(vhook['clips'])}")
    # правило замовника (13.10): спікерка між двома перебивками не мелькає коротше MIN_SPEAKER_GAP —
    # такі «вставки на 0,3 с» виглядають дешево й мерехтять; перебивки ставимо встик
    MIN_SPEAKER_GAP = float(os.environ.get("MIN_SPEAKER_GAP", "1.0"))
    def _clip_len(clip):
        f = INPUT_BROLL / clip
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return float("inf")
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True)
        try: return float(r.stdout.strip())
        except ValueError: return 0.0
    _bl = sorted(cut["broll"], key=lambda x: x["start"])
    for _p, _n in zip(_bl, _bl[1:]):
        _gap = _n["start"] - (_p["start"] + _p["dur"])
        if 0 < _gap < MIN_SPEAKER_GAP:
            if _p.get("clip_start", 0) + _p["dur"] + _gap <= _clip_len(_p["clip"]):
                _p["dur"] += _gap
            else:
                _n["start"] -= _gap; _n["dur"] += _gap
            print(f"  перебивки встик: {_p['start'] + off:5.1f} с — прибрано мелькання спікерки {_gap:.2f} с")
    # встик = з нахлестом в 1 кадр: при округленні до кадрів між «встик» перебивками лишався кадр спікера (36.1, 14,08 с)
    for _p, _n in zip(_bl, _bl[1:]):
        _gap = _n["start"] - (_p["start"] + _p["dur"])
        if -0.001 < _gap < MIN_SPEAKER_GAP:
            _n["start"] -= 1.0 / fps; _n["dur"] += 1.0 / fps; _n["clip_start"] = max(0.0, _n.get("clip_start", 0) - 1.0 / fps)
    # стиль vit (топ-креативи клієнта): перебивка не довше broll_max — довшу ріжемо на кілька кадрів того ж кліпу
    # зі стрибком 0,4 с усередині кліпу: темп 5–7 склейок на 10 с, як у вінерах
    if st.get("broll_max"):
        split = []
        for b in sorted(cut["broll"], key=lambda x: x["start"]):
            n = math.ceil(b["dur"] / st["broll_max"] - 1e-6)
            if n <= 1:
                split.append(b)
                continue
            piece, cs, clen = b["dur"] / n, b.get("clip_start", 0), _clip_len(b["clip"])
            for k in range(n):
                jump = 0.4 if cs + piece + 0.4 + piece * (n - k - 1) <= clen else 0.0
                split.append({**b, "start": b["start"] + k * piece, "dur": piece, "clip_start": cs})
                cs += piece + jump
            print(f"  vit: перебивка {b['clip']} {b['dur']:.1f} с → {n} шматки")
        cut["broll"] = split
    from plan import load_catalog
    pip_files = {c["file"] for c in load_catalog() if c.get("pip")}
    broll, to_reframe = [], []
    for i, b in enumerate(cut["broll"]):
        src = INPUT_BROLL / b["clip"]
        ext = src.suffix.lower()
        kind = "photo" if ext in (".jpg", ".jpeg", ".png", ".webp") else "video"
        fvar = src.with_name(f"{src.stem}_{a.fmt}{src.suffix}")  # 23.10: окремий варіант під формат (case_*_4x5.png)
        if kind == "photo" and fvar.exists():
            src = fvar
        dst_name = f"broll/{i:02d}_{b['clip']}" if kind == "photo" else f"broll/{i:02d}_{src.stem}.mp4"
        if kind == "video" and ext != ".mp4":  # браузерний рендер надійніше читає mp4 без повороту в метаданих
            conv = WORK / f"_rm_{src.stem}.mp4"
            if not conv.exists():
                subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(src), "-an", "-vf", "scale='if(gt(iw,ih),1920,1080)':-2",
                                "-c:v", VENC, "-b:v", "12M", str(conv)], check=True)
            src = conv
        link(src, pub / dst_name)
        item = {"file": f"{rid}/{dst_name}", "kind": kind, "start": b["start"] + off, "dur": b["dur"],
                "clipStart": b.get("clip_start", 0), "portrait": is_portrait(src), "idx": i,
                "pip": a.style == "vit" and b["clip"] in pip_files,
                # картка з власним текстом (card_*): субтитри поверх неї не показуємо, як у рефах дизайнер
                "card": "_card_" in b["clip"] or bool(False)}
        if not item["portrait"]:  # горизонтальна — під неї готовий розмитий фон замість CSS-розмиття в кожному кадрі
            bg = blurred_bg(src, kind, ow, oh)
            link(bg, pub / "broll" / f"{i:02d}_bg{bg.suffix}")
            item["bg"] = f"{rid}/broll/{i:02d}_bg{bg.suffix}"
            sw, sh = media_size(src)
            to_reframe.append({"key": i, "path": str(src), "kind": kind, "t0": item["clipStart"],
                               "t1": item["clipStart"] + item["dur"], "aspect": ow / oh, "srcW": sw, "srcH": sh})
        broll.append(item)
    # горизонтальні з обличчям — кадруємо у вертикаль за обличчям (без розмитих полів), як монтажер
    lowres_files = {c["file"]: c.get("lowres", False) for c in load_catalog()}
    MAX_UPSCALE = 2.0  # видима смуга джерела розтягується до ширини кадру; сильніше — «мило» (старі фото 640 px)
    for r in reframe(to_reframe):
        src_info = next(x for x in to_reframe if x["key"] == r["key"])
        upscale = ow / max(1, r["visible"] * src_info["srcW"])
        # старі фото й скани (lowres у каталозі) збільшені при імпорті з ~640 px: кадрування дасть «мило».
        # Метрики різкості тут не працюють — ретушоване студійне фото так само «гладке», як розмите старе.
        lowres = lowres_files.get(cut["broll"][r["key"]]["clip"], False)
        if r["fits"] and upscale <= MAX_UPSCALE and not lowres:
            it = broll[r["key"]]
            it.update({"focus": r["path"], "srcW": src_info["srcW"], "srcH": src_info["srcH"]})

    # короткий хук (< 1,5 с) у варіанті text: одразу після нього — стокова вставка 0,6–1 с
    if vhook and a.vhook == "text" and vhook["end"] - off < 1.5 and vhook["clips"]:
        hs = vhook["end"]
        nxt_b = min((b["start"] for b in broll if b["start"] >= hs - 0.01), default=total)
        if nxt_b - hs >= 0.6:
            dur = 0.8 if nxt_b - hs > 0.8 + 1.0 else nxt_b - hs + 1.0 / fps  # встик з наступною перебивкою
            broll.append({"file": vhook["clips"][0]["file"], "kind": "video", "start": hs, "dur": round(min(dur, 1.0), 3),
                          "clipStart": 1.0, "portrait": True, "idx": len(broll), "pip": False})
            broll.sort(key=lambda b: b["start"])
            print(f"  короткий хук: стокова вставка {hs:.2f}–{hs + min(dur, 1.0):.2f} с")

    # контроль стиків: відкриті помітні стики — закрити перебивкою / наїзд; дублі — вирівняти яскравість
    from joins import check as check_joins
    join_report, join_zooms, join_gains = check_joins(str(rm_master), fps, starts, cut["timeline"], off, path, cw, ch,
                                                      faces, broll, total)
    for r in join_report:
        if r["action"] != "ок":
            print(f"  стик {r['t']:5.1f} с (вирізано {r['removed']:.1f} с): {r['action']}")

    overlays = []
    for o in cut.get("overlays", []):
        item = {"type": o["type"], "start": o["start"] + off, "end": o["end"] + off}
        overlays.append(item)
    if a.hook_title:
        overlays.append({"type": "title", "start": 0.0, "end": off, "text": a.hook_title})

    # звук: чистка, нормалізація, ефекти на вставках (той самий audio.py)
    # звуки монтажера: клік під кожну перебивку (по черзі «клік»/«клік 2»/«кнопка»), «вжух» на свайп стрічки,
    # «камера» на її спалах, «enter» на стрілки заклику, довгий «вжух» на наїзд хука-питання
    events = [(b["start"], "pop") for b in broll]
    for o in overlays:
        if o["type"] == "cta_arrows":
            events.append((o["start"], "enter"))
        elif o["type"] == "title" and off > 0.5:
            events.append((0.0, "whoosh_long", off + 0.3))
    if vhook:  # «вжух» на виході зі сплітів / «клік» на різкому зумі ключового слова
        events.append((vhook["end"], "whoosh") if a.vhook == "split" else (vhook["keyAt"], "pop"))
    events.sort(key=lambda e: e[0])
    audio = WORK / f"{rid}_rm_audio.m4a"
    render_audio(str(master), events, total, pick_music(a.music), audio, gap=a.music_gap)
    link(audio, pub / "audio.m4a")
    link(ROOT / "fonts" / "Montserrat-ExtraBold.ttf", RM / "public" / "fonts" / "Montserrat-ExtraBold.ttf")
    link(ROOT / "fonts" / "Montserrat-Bold.ttf", RM / "public" / "fonts" / "Montserrat-Bold.ttf")
    link(ROOT / "fonts" / "Montserrat-Black.ttf", RM / "public" / "fonts" / "Montserrat-Black.ttf")

    # затемнення під текст — лише для стилю без плашки (pyshka): плашка box читається на будь-якому фоні.
    # Монтажер: 10–20%, тільки коли текст зливається з фоном — рахуємо окремо для спікерки й кожної перебивки
    dims = {}
    if a.style not in ("box", "vit"):  # vit — текст з обведенням, читається й так
        dims["speaker"] = dim_alpha(str(rm_master))
        for i, b in enumerate(cut["broll"]):
            src_b = INPUT_BROLL / b["clip"]
            dims[i] = dim_alpha(str(src_b))
        for i, it in enumerate(broll):
            it["dim"] = dims.get(i, 0.0)
    # наклейки (правка 21.10): work/<name>.stickers.json = [{"i": номер слова, "png": "x.png", "side": "l"|"r", "dur": 1.6}]
    # PNG-ілюстрації з білою обводкою з input/stickers/; зʼявляються на слові i, з боків над обличчям
    stickers = []
    sp = WORK / f"{a.name}.stickers.json"
    if sp.exists():  # 22.10: і для спікера (box)
        wstart = {w["i"]: w["start"] for w in words if "i" in w}
        for k, s_ in enumerate(json.loads(sp.read_text())):
            t0 = wstart.get(s_["i"])
            if t0 is None:
                continue
            link(DATA / "input" / "stickers" / s_["png"], pub / "stickers" / s_["png"])
            stickers.append({"file": f"{rid}/stickers/{s_['png']}", "start": round(t0, 3), "dur": s_.get("dur", 1.6),
                             "side": s_.get("side", "r" if k % 2 else "l"), "idx": k})
    # плашки-ключові слова (22.10, як у рефах автор): work/<name>.plates.json = [{"from": i, "to": i, "text": "…", "color": "red|yellow|green|blue"}]
    # великий кольоровий капс з білою обводкою посеред кадру; поки плашка на екрані — субтитри сховані
    plates = []
    pp = WORK / f"{a.name}.plates.json"
    if pp.exists():
        wst = {w["i"]: w["start"] for w in words if "i" in w}
        wen = {w["i"]: w["end"] for w in words if "i" in w}
        for pl in json.loads(pp.read_text()):
            t0, t1 = wst.get(pl["from"]), wen.get(pl["to"])
            if t0 is None or t1 is None:
                continue
            plates.append({"start": round(t0 - 0.05, 3), "end": round(max(t1 + 0.25, t0 + 1.2), 3), "text": pl["text"],
                           "color": pl.get("color", "red"), "keep": bool(pl.get("keep_captions"))})
    # MONTAGE_BROLL_FILL=1: горизонтальні без обличчя — на весь кадр по центру (як у designer), без розмитих полів
    if os.environ.get("MONTAGE_BROLL_FILL") == "1":
        for it in broll:
            if not it.get("portrait") and not it.get("focus"):
                it["portrait"] = True
    # MONTAGE_PHRASE_ZOOM="0-24": як у рефах-«говорящих головах» (автор кадру) — кожна фраза новим планом:
    # на межах речень різко чергуємо загальний / середній план (1.0 ↔ 1.32) у вікні секунд тіла (правка 21.10)
    phrase_zoom = []
    if os.environ.get("MONTAGE_PHRASE_ZOOM"):
        z0, z1 = (float(x) + off for x in os.environ["MONTAGE_PHRASE_ZOOM"].split("-"))
        mwz = merge_tokens(words)
        bounds = [z0] + [mwz[k + 1]["start"] - 0.04 for k in range(len(mwz) - 1)
                         if z0 < mwz[k + 1]["start"] < z1 and re.search(r"[.!?…:—–-][»\"')]*$", mwz[k]["w"].strip())] + [z1]
        for k in range(len(bounds) - 1):
            phrase_zoom.append([round(bounds[k], 3), round(bounds[k + 1], 3), float(os.environ.get("MONTAGE_PHRASE_ZOOM_K", "1.32")) if k % 2 else 1.0])
    props = {"fps": fps, "width": ow, "height": oh, "durationInFrames": int(round(total * fps)),
             **({"phraseZoom": phrase_zoom} if phrase_zoom else {}),
             "dimSpeaker": dims.get("speaker", 0.0),
             "joinZooms": join_zooms, "joinGains": join_gains,
             "master": f"{rid}/master_{a.fmt}.mp4", "audio": f"{rid}/audio.m4a", "masterW": mW, "masterH": mH,
             "crop": {"w": cw, "h": ch, "path": [[round(t, 2), x, y] for t, x, y in path]},
             "faceY": st.get("face_y", 0.3), "faceYReal": face_y_real, "cuts": [round(s, 3) for s in starts],
             "style": a.style, "subBottom": float(os.environ["SUB_BOTTOM_" + a.fmt.upper()]) if os.environ.get("SUB_BOTTOM_" + a.fmt.upper()) else st["bottom"][a.fmt], "groups": groups, "boxColor": a.box_color,
             "broll": broll, "overlays": overlays, **({"vhook": vhook} if vhook else {}),
             # MONTAGE_BANNER: постійна зелена плашка на весь ролик (стиль vit), напр. «ПЕРСОНАЖ?» — правка 20.10
             **({"banner": os.environ["MONTAGE_BANNER"]} if os.environ.get("MONTAGE_BANNER") else {}),
             **({"stickers": stickers} if stickers else {}), **({"plates": plates} if plates else {}),
             # MONTAGE_SOFT=1 (правки замовника 22.10): світлі плашки з округлими кутами, наклейки-фото, одне за раз
             **({"soft": True} if os.environ.get("MONTAGE_SOFT") == "1" else {}),
             **({"plateTop": float(os.environ["MONTAGE_PLATE_TOP_" + a.fmt.upper()])} if os.environ.get("MONTAGE_PLATE_TOP_" + a.fmt.upper()) else {})}
    (RM / "props").mkdir(exist_ok=True)
    dst = RM / "props" / f"{rid}_{a.fmt}.json"
    dst.write_text(json.dumps(props, ensure_ascii=False))
    print(f"→ {dst} | {total:.1f} с, перебивок {len(broll)}, груп субтитрів {len(groups)}, точок кадрування {len(path)}")
    if a.render:
        render_rm("Creative", dst, a.render, a.scale)
        print("→", a.render)
