"""Фінальний рендер форматів: рефрейм → перебивки → субтитри.

Використання: python render.py <name> [--formats 9x16,4x5]
Потрібні: work/<name>.cut.json (cut.py), work/<name>.faces.json (track.py)
Результат: output/<name>_9x16.mp4, output/<name>_4x5.mp4
"""
import argparse
import json
import re
import subprocess

from audio import events_from_cut, pick_music, render_audio
from grade import dim_alpha, dim_layer_pgm, grade_filter
from overlays import apply as apply_overlays, clip_input, is_portrait, kenburns
from config import ENCODE_V, FFMPEG, FFPROBE, FONTS_DIR, INPUT_BROLL, OUTPUT, WORK, ff_path

FORMATS = {"9x16": (1080, 1920), "4x5": (1080, 1350)}

# Стилі субтитрів. Кольори ASS: &HAABBGGRR. bottom — відступ знизу, частка висоти кадру.
STYLES = {
    # великий капс із жовтою підсвіткою активного слова
    "reels": dict(font="Montserrat ExtraBold", size=0.088, color="&H00FFFFFF", active="&H000AD6FF",
                  outline=0.09, shadow=0.04, blur=0, max_words=3, max_chars=18,
                  bottom={"9x16": 0.30, "4x5": 0.16}, look=False),
    # агент: дрібний білий капс на рівні грудей, без підсвітки, мʼяка тінь,
    # теплий кольорокор і затемнення знизу (знято з july_16.1_kheiteri)
    "pyshka": dict(font="Montserrat Bold", size=0.050, color="&H00FFFFFF", active=None,
                   outline=0.04, shadow=0, blur=5, max_words=2, max_chars=16, emph_scale=130,
                   bottom={"9x16": 0.475, "4x5": 0.44}, look=True,
                   face_h={"9x16": 0.135, "4x5": 0.175}, face_y=0.30, max_zoom=1.6),
    # Submagic-подібний: жирний білий текст на кольоровій плашці (колір плашки — під палітру відео:
    # монтажер вибирає за кольорами зйомки; тут темно-зелена, як у ролику 4.1)
    "box": dict(font="Montserrat ExtraBold", size=0.052, color="&H00FFFFFF", active=None,
                outline=0.30, shadow=0, blur=0, max_words=3, max_chars=20, emph_scale=None,
                bottom={"9x16": 0.44, "4x5": 0.40}, look=True, border_style=3, outline_color="&H003C5C32",
                face_h={"9x16": 0.135, "4x5": 0.175}, face_y=0.30, max_zoom=1.4),
    # клієнт (топ-креативи jan_hg 5.1/6.1/9.1): білий жирний курсивний капс з чорним обведенням, 1–3 слова,
    # по центру нижче обличчя; перебивки-скріни з кружечком спікера (pip у каталозі), по 2–3 с
    "vit": dict(font="Montserrat Black", size=0.075, color="&H00FFFFFF", active=None,
                outline=0.08, shadow=0, blur=0, max_words=3, max_chars=16, emph_scale=None,
                bottom={"9x16": 0.36, "4x5": 0.24}, look=True,
                face_h={"9x16": 0.135, "4x5": 0.175}, face_y=0.30, max_zoom=1.4,
                broll_max=3.0, pause=3.0),
}
SUB_GAP_BREAK = 0.35
HANGING = {"і", "й", "та", "а", "але", "чи", "що", "як", "бо", "щоб", "коли", "якщо", "не", "ні", "це",
           "в", "у", "на", "за", "з", "із", "зі", "до", "від", "для", "по", "про", "під", "над", "при", "без",
           "и", "но", "или", "что", "как", "если", "когда", "к", "с", "о", "от", "из", "это", "то"}

# Рефрейм
FACE_Y = 0.38        # де тримати центр обличчя по висоті кадру
FACE_HOLD = 0.6      # скільки тримати останню позицію, коли обличчя зникло
SMOOTH = 0.25        # EMA на 10 Гц
DEADZONE = 0.02


def probe_size(video):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
                       capture_output=True, text=True, check=True)
    w, h = r.stdout.strip().split(",")[:2]
    return int(w), int(h)


# ---------- рефрейм ----------

def crop_box(W, H, ow, oh):
    if W / H > ow / oh:
        return round(H * ow / oh) // 2 * 2, H
    return W, round(W * oh / ow) // 2 * 2


def crop_path(faces, cut_starts, W, H, cw, ch, FACE_Y=FACE_Y):
    """Позиції кропу (t, x, y). На монтажних стиках згладжування скидається — камера «стрибає» разом зі склейкою."""
    cx0, cy0 = (W - cw) / 2, (H - ch) / 2
    path, last_face_t, last = [], -1e9, None
    sx = sy = None
    bounds = sorted(cut_starts)
    for f in faces:
        t = f[0]
        if f[1] is not None:
            tx = f[1] * W - cw / 2
            ty = f[2] * H - ch * FACE_Y
            last, last_face_t = (tx, ty), t
        elif last and t - last_face_t <= FACE_HOLD:
            tx, ty = last
        else:
            tx, ty = cx0, cy0
        tx, ty = min(max(tx, 0), W - cw), min(max(ty, 0), H - ch)
        new_piece = any(prev < b <= t for b in bounds for prev in [path[-1][0] if path else -1])
        if sx is None or new_piece:
            sx, sy = tx, ty
        else:
            if abs(tx - sx) > DEADZONE * W:
                sx += (tx - sx) * SMOOTH
            if abs(ty - sy) > DEADZONE * H:
                sy += (ty - sy) * SMOOTH
        path.append((t, int(sx) // 2 * 2, int(sy) // 2 * 2))
    return path


def write_sendcmd(path, dst):
    lines, prev = [], None
    for t, x, y in path:
        if (x, y) != prev:
            lines.append(f"{t:.3f} crop@rf x {x}, crop@rf y {y};")
            prev = (x, y)
    dst.write_text("\n".join(lines))


# ---------- субтитри ----------

def merge_tokens(words):
    """Whisper ріже «стоп-лосс», «0.01», «4,693» на кілька токенів — склеюємо назад."""
    out = []
    for w in words:
        if out and re.match(r"^[-.,]\S", w["w"]) and (w["w"][0] == "-" or w["w"][1].isdigit()):
            out[-1] = {**out[-1], "w": out[-1]["w"] + w["w"], "end": w["end"]}
        else:
            out.append(dict(w))
    return out


def group_words(words, st):
    SUB_MAX_WORDS, SUB_MAX_CHARS = st["max_words"], st["max_chars"]
    groups, cur = [], []
    for w in words:
        text_len = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
        gap = w["start"] - cur[-1]["end"] if cur else 0
        if cur and (len(cur) >= SUB_MAX_WORDS or text_len > SUB_MAX_CHARS or gap > SUB_GAP_BREAK):
            groups.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.?!]$", w["w"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    # сполучник чи прийменник не лишаємо висіти в кінці рядка — переносимо в наступний
    for i in range(len(groups) - 1):
        g, nxt = groups[i], groups[i + 1]
        while (len(g) > 1 and clean(g[-1]["w"]).lower() in HANGING
               and not re.search(r"[.?!,]$", g[-1]["w"])
               and nxt[0]["start"] - g[-1]["end"] <= SUB_GAP_BREAK):
            nxt.insert(0, g.pop())
    return groups


PUNCT = r"[,.:;!?…«»\"“”()\[\]—–]"


def clean(word):
    """Субтитри без розділових знаків (правило монтажера); апостроф і дефіс усередині слова лишаються."""
    return re.sub(rf"^{PUNCT}+|{PUNCT}+$", "", word.strip()).upper()


def ass_time(t):
    t = max(0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def build_ass(words, fmt, ow, oh, total, st):
    size = round(ow * st["size"])
    margin_v = round(oh * st["bottom"][fmt])
    SUB_FONT, SUB_COLOR, SUB_ACTIVE = st["font"], st["color"], st["active"]
    pre = f"{{\\blur{st['blur']}}}" if st["blur"] else ""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {ow}
PlayResY: {oh}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{SUB_FONT},{size},{SUB_COLOR},{SUB_COLOR},{st.get("outline_color", "&H78000000")},&H80000000,0,0,0,0,100,100,0,0,{st.get("border_style", 1)},{round(size * st["outline"], 1)},{round(size * st["shadow"], 1)},2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    groups = group_words([w for w in merge_tokens(words) if w["w"].strip()], st)
    events = []
    for gi, g in enumerate(groups):
        g_end = g[-1]["end"] + 0.25
        if gi + 1 < len(groups):
            g_end = min(g_end, groups[gi + 1][0]["start"])
        g_end = min(g_end, total)
        if not SUB_ACTIVE:  # без підсвітки — одна подія на групу
            bits = []
            for x in g:
                t = clean(x["w"])
                if x.get("emph") and st.get("emph_scale"):  # ключові слова — більшим розміром
                    sc = st["emph_scale"]
                    t = f"{{\\fscx{sc}\\fscy{sc}}}{t}{{\\fscx100\\fscy100}}"
                bits.append(t)
            text = " ".join(bits)
            events.append(f"Dialogue: 0,{ass_time(g[0]['start'])},{ass_time(g_end)},Sub,,0,0,0,,{pre}{text}")
            continue
        for j, w in enumerate(g):
            s = w["start"]
            e = g[j + 1]["start"] if j + 1 < len(g) else g_end
            if e - s < 0.04:
                continue
            parts = []
            for k, x in enumerate(g):
                if k == j:
                    parts.append(f"{{\\c{SUB_ACTIVE}\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}}"
                                 f"{clean(x['w'])}{{\\r}}")
                else:
                    parts.append(clean(x["w"]))
            events.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Sub,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(events) + "\n"


# ---------- рендер ----------

def render(name, fmt, cut, st, music=None):
    ow, oh = FORMATS[fmt]
    master = cut["master"]
    W, H = probe_size(master)
    cw, ch = crop_box(W, H, ow, oh)
    faces = json.loads((WORK / f"{name}.faces.json").read_text())
    # наїзд: якщо стиль задає розмір обличчя, підрізаємо план під нього (медіана по ролику)
    heights = sorted(f[3] for f in faces if f[1] is not None)
    if st.get("face_h") and heights:
        target_ch = heights[len(heights) // 2] * H / st["face_h"][fmt]  # висота кропу, за якої обличчя займе face_h кадру
        zoom = min(st["max_zoom"], max(1.0, ch / target_ch))
        cw, ch = int(cw / zoom) // 2 * 2, int(ch / zoom) // 2 * 2

    inputs = ["-i", master]
    filters = []
    base = f"scale={ow}:{oh}:flags=lanczos,setsar=1"
    if st["look"]:
        base += f",{grade_filter(master)}"  # адаптивно під відео: тіні, світло, контраст
    if (cw, ch) != (W, H):
        path = crop_path(faces, [p["dst_start"] for p in cut["timeline"]], W, H, cw, ch,
                         st.get("face_y", FACE_Y))
        cmd_file = WORK / f"{name}_{fmt}.sendcmd"
        write_sendcmd(path, cmd_file)
        filters.append(f"[0:v]sendcmd=f='{cmd_file}',crop@rf={cw}:{ch}:{path[0][1]}:{path[0][2]},{base}[v0]")
    else:
        filters.append(f"[0:v]{base}[v0]")

    overlays = cut.get("overlays", [])
    cur = "v0"
    for bi, b in enumerate(cut["broll"]):
        k = inputs.count("-i")
        clip = INPUT_BROLL / b["clip"]
        inputs += clip_input(clip, b.get("clip_start", 0), b["dur"], cut["fps"])
        b0, b1 = b["start"], b["start"] + b["dur"]
        kb = kenburns(clip, ow, oh, cut["fps"], b["dur"], bi)
        if is_portrait(clip):
            # вертикальний кліп — на весь кадр (верх кадру в пріоритеті: там обличчя)
            filters.append(
                f"[{k}:v]fps={cut['fps']},scale={ow}:{oh}:force_original_aspect_ratio=increase,"
                f"crop={ow}:{oh}:(iw-ow)/2:(ih-oh)*0.25,setsar=1{kb},setpts=PTS-STARTPTS+{b0}/TB[br{k}];"
                f"[{cur}][br{k}]overlay=enable='between(t,{b0:.3f},{b1:.3f})':eof_action=pass[v{k}]")
        else:
            # горизонтальний/квадратний — цілком по ширині на розмитому фоні, без обрізання
            filters.append(
                f"[{k}:v]fps={cut['fps']},split[bb{k}][bf{k}];"
                f"[bb{k}]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},boxblur=30:2[bg{k}];"
                f"[bf{k}]scale={ow}:{oh}:force_original_aspect_ratio=decrease[fg{k}];"
                f"[bg{k}][fg{k}]overlay=(W-w)/2:(H-h)/2,setsar=1{kb},setpts=PTS-STARTPTS+{b0}/TB[br{k}];"
                f"[{cur}][br{k}]overlay=enable='between(t,{b0:.3f},{b1:.3f})':eof_action=pass[v{k}]")
        cur = f"v{k}"

    if st["look"]:
        # затемнення ТІЛЬКИ коли текст зливається з фоном (10–20%); на темному фоні його немає зовсім
        alpha = dim_alpha(master)
        if alpha > 0.02:
            grad = WORK / f"_dim_{fmt}.pgm"
            dim_layer_pgm(ow, oh, alpha, 1 - st["bottom"][fmt] - 0.015, grad)
            gi = inputs.count("-i")
            inputs += ["-i", str(grad)]
            filters.append(f"[{gi}:v]scale={ow}:{oh},format=gray[ga];"
                           f"color=black:s={ow}x{oh}:r={cut['fps']}[gc];[gc][ga]alphamerge[gr];"
                           f"[{cur}][gr]overlay=shortest=1[vg]")
            cur = "vg"

    for o in overlays:
        cur = apply_overlays([o], fmt, ow, oh, cut["fps"], inputs, filters, cur, None)

    ass = WORK / f"{name}_{fmt}.ass"
    ass.write_text(build_ass(cut["words"], fmt, ow, oh, cut["duration"], st))
    filters.append(f"[{cur}]ass='{ff_path(ass)}':fontsdir='{ff_path(FONTS_DIR)}'[vout]")

    fc = WORK / f"{name}_{fmt}.filter.txt"
    fc.write_text(";\n".join(filters))
    OUTPUT.mkdir(exist_ok=True)
    dst = OUTPUT / f"{name}_{fmt}.mp4"
    vtmp, atmp = WORK / f"_{name}_{fmt}.video.mp4", WORK / f"_{name}_{fmt}.audio.m4a"
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", *inputs, "-/filter_complex", str(fc),
                    "-map", "[vout]", "-an", *ENCODE_V, str(vtmp)], check=True)
    render_audio(master, events_from_cut(cut), cut["duration"], music, atmp)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(vtmp), "-i", str(atmp), "-map", "0:v", "-map", "1:a",
                    "-c", "copy", "-shortest", "-movflags", "+faststart", str(dst)], check=True)
    vtmp.unlink(); atmp.unlink()
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--formats", default="9x16,4x5")
    ap.add_argument("--style", default="reels", choices=STYLES)
    ap.add_argument("--music", default=None, help="файл музики або auto (input/audio/music)")
    a = ap.parse_args()
    cut = json.loads((WORK / f"{a.name}.cut.json").read_text())
    for fmt in a.formats.split(","):
        print("→", render(a.name, fmt, cut, STYLES[a.style], pick_music(a.music)))
