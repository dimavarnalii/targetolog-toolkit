# -*- coding: utf-8 -*-
"""Ad-creative montage from raw phone takes (proxies 1080x1920 / 30 fps).

Run it FROM THE PROJECT FOLDER (<VM_ROOT>/projects/<name>/), where creatives.json, proxy/ and
*.words_m.json live:
    python <package>/ad_creatives/build_creative.py creatives.json <name> [<name> ...]   (or "all") [--subs-only]

Pipeline per creative:
  1. words_m.json -> keep-segments (drops long pauses + `exclude` ranges = bad takes)
  2. ffmpeg: trim/concat segments of the 1080x1920 proxy, punch-in zoom alternating per
     shot (hides jump cuts), full-frame B-roll cutaways with Ken Burns + whoosh,
     music bed ducked under voice, loudnorm  -> _comp.mp4 (no text)
  3. ASS captions (2-3 words, keyword highlight + pop) + hook plate, rendered twice:
     9:16 1080x1920 and 4:5 1080x1350 (center crop)
Music and whoosh are used only if VM_MUSIC / VM_WHOOSH point to your own files (see vm_config.py).
"""
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vm_config as vm  # noqa: E402

FF = vm.FFMPEG
FFPROBE = vm.FFPROBE
PROJ = Path.cwd()  # the project folder you run the script from
FPS = 30
W, H = 1080, 1920
H45 = 1350
Y45 = (H - H45) // 2  # crop offset for 4:5

GAP_MAX = 0.30    # pauses longer than this get cut
PAD_IN = 0.06     # keep a little air before a word
PAD_OUT = 0.10    # ... and after
ZOOM = 1.12       # punch-in factor on alternating shots
SHOT_MIN = 2.2    # min seconds before zoom state may flip


def run(cmd, log=None):
    print("  $", " ".join(str(c) for c in cmd)[:300])
    if log:
        with open(log, "w", encoding="utf-8") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    else:
        r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed ({r.returncode}) {log or ''}")


def probe_dur(p):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def in_ranges(t, ranges):
    return any(a <= t < b for a, b in ranges)


def build_segments(words, exclude, src_dur):
    ws = [w for w in words if not in_ranges((w["start"] + w["end"]) / 2, exclude)]
    segs = []
    for w in ws:
        s, e = max(0.0, w["start"] - PAD_IN), min(src_dur, w["end"] + PAD_OUT)
        if segs and s - segs[-1][1] <= GAP_MAX - PAD_IN - PAD_OUT:
            segs[-1][1] = max(segs[-1][1], e)
        else:
            if segs and s < segs[-1][1]:
                s = segs[-1][1]
            segs.append([s, e])
    # never cut inside an excluded range boundary mid-word: clamp
    out = []
    for s, e in segs:
        for a, b in exclude:
            if s < a < e:
                e = a
            if s < b < e:
                s = b
        if e - s > 0.12:
            out.append([round(s, 3), round(e, 3)])
    return ws, out


TARGET_WPS = 3.0   # цільовий темп чистої мови, слів/с (за практикою монтажера: ~3 с/слів, не швидше +25%)
MAX_SPEED = 1.25


def pick_speed(cfg, n_words, total_raw):
    """"speed" у creatives.json: число (1.1), 1 (без прискорення) або "auto" (за замовчуванням).
    auto: повільну мову підтягуємо до ~3 слів/с, але не швидше x1.25; швидку мову не чіпаємо."""
    v = cfg.get("speed", "auto")
    if v == "auto":
        wps = n_words / total_raw if total_raw > 0 else TARGET_WPS
        return round(min(MAX_SPEED, max(1.0, TARGET_WPS / wps)), 2) if wps > 0 else 1.0
    return float(v)


def src_to_out(t, segs):
    acc = 0.0
    for s, e in segs:
        if t < s:
            return acc
        if t <= e:
            return acc + (t - s)
        acc += e - s
    return acc


def fix_words(ws, fixes, fix_at):
    # each fix_at hits only the single word whose start is nearest to t0 (within 0.15s)
    targets = {}
    for t0, new in fix_at:
        k = min(range(len(ws)), key=lambda j: abs(ws[j]["start"] - t0))
        if abs(ws[k]["start"] - t0) < 0.15:
            targets[k] = new
    out = []
    for j, w in enumerate(ws):
        w = dict(w)
        txt = targets.get(j, w["word"])
        key = re.sub(r"[^\w$%+-]", "", txt.lower())
        if key in fixes:
            punct = re.sub(r"^[\w$%+-]+", "", re.sub(r"^\W+", "", txt))
            txt = fixes[key] + (punct if not re.search(r"\W$", fixes[key]) else "")
        w["word"] = txt
        if txt.startswith("-") and len(txt) > 1 and out and w["start"] - out[-1]["end"] < 0.3:
            # whisper splits hyphenated words ("из -за", "какая -то") -> glue back
            out[-1]["word"] += txt
            out[-1]["end"] = w["end"]
            continue
        if txt:
            out.append(w)
    return out


# ---------------- captions ----------------

def fmt_ts(t):
    t = max(0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def group_words(ws):
    groups, cur = [], []
    for i, w in enumerate(ws):
        if cur and (w["start"] - cur[-1]["end"] > 0.35):
            groups.append(cur); cur = []
        cur.append(w)
        n_chars = sum(len(x["word"]) for x in cur) + len(cur) - 1
        nxt = ws[i + 1]["word"] if i + 1 < len(ws) else ""
        ends_sentence = re.search(r"[.!?,:;]$", w["word"])
        if len(cur) >= 3 or n_chars + 1 + len(nxt) > 16 or ends_sentence:
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    return groups


def is_kw(word, stems):
    clean = re.sub(r"[^\w$%+]", "", word.lower())
    return any(clean.startswith(s.lower()) for s in stems)


def build_ass(ws_out, cfg, fmt, total):
    if fmt == "916":
        resy, cap_y, hook_y = H, 1380, 330
    else:
        resy, cap_y, hook_y = H45, 1010, 120
    stems = cfg.get("keywords", [])
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {resy}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{vm.ASS_FONT},90,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,4,5,50,50,0,204
Style: Hook,{vm.ASS_FONT},70,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,22,0,8,70,70,{hook_y},204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [hdr]
    hook = cfg.get("hook")
    if hook:
        hd = cfg.get("hook_dur", 4.5)  # author's rule: hook stays 4.5 s (the original code default was 3.2)
        txt = hook.replace("\n", "\\N")
        # black plate, white text, keyword line in yellow via {\c}
        txt = re.sub(r"\*(.+?)\*", r"{\\c&H0000E5FF&}\1{\\c&H00FFFFFF&}", txt)
        lines.append(f"Dialogue: 1,{fmt_ts(0)},{fmt_ts(hd)},Hook,,0,0,0,,"
                     f"{{\\3c&H00000000&\\fad(0,200)\\t(0,120,\\fscx108\\fscy108)\\t(120,240,\\fscx100\\fscy100)}}{txt}\n")
    groups = group_words(ws_out)
    for i, g in enumerate(groups):
        st = g[0]["start"]
        en = g[-1]["end"]
        if i + 1 < len(groups):
            en = min(max(en, groups[i + 1][0]["start"] - 0.01), groups[i + 1][0]["start"])
        en = min(en + 0.15, total) if i + 1 == len(groups) else en
        parts = []
        has_kw = False
        for w in g:
            wd = w["word"].upper().strip()
            wd = re.sub(r"^[-–]+", "", wd)
            wd = re.sub(r"[.,;:]+$", "", wd)  # no trailing punctuation on screen, keep ?!
            if is_kw(w["word"], stems):
                has_kw = True
                parts.append(f"{{\\c&H0000E5FF&\\fscx112\\fscy112}}{wd}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
            else:
                parts.append(wd)
        text = " ".join(parts)
        vis_len = sum(len(w["word"]) for w in g) + len(g) - 1
        if vis_len > 13:  # long group: shrink to fit 1080 width (Arial Black caps ~68px/char at 90)
            text = f"{{\\fs{int(90 * 13 / vis_len)}}}" + text
        pop ="\\t(0,90,\\fscx106\\fscy106)\\t(90,180,\\fscx100\\fscy100)" if has_kw else \
              "\\fscx92\\fscy92\\t(0,100,\\fscx100\\fscy100)"
        lines.append(f"Dialogue: 0,{fmt_ts(st)},{fmt_ts(en)},Cap,,0,0,0,,{{\\pos({W // 2},{cap_y}){pop}}}{text}\n")
    return "".join(lines)


# ---------------- composite ----------------

def zoom_intervals(ws_out, segs, total):
    """Alternate 1.0 / ZOOM shots, flipping on a word start (or a cut) every ~SHOT_MIN..SHOT_MIN+1s."""
    cuts, acc = [], 0.0
    for s, e in segs:
        acc += e - s
        cuts.append(acc)
    cand = sorted(set([round(w["start"], 3) for w in ws_out] + [round(c, 3) for c in cuts[:-1]]))
    bounds, last = [0.0], 0.0
    for t in cand:
        is_cut = any(abs(t - c) < 0.02 for c in cuts)
        if (is_cut and t - last >= 1.2) or t - last >= SHOT_MIN + 0.8:
            bounds.append(t); last = t
    bounds.append(total)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if i % 2 == 1]


def build_comp(cfg, segs, total, out_path, cut_out, ws_out, speed=1.0):
    src = str(PROJ / cfg["source"])
    fl = []
    for i, (s, e) in enumerate(segs):
        fl.append(f"[0:v]trim={s}:{e},setpts=PTS-STARTPTS,setsar=1[v{i}];")
        fl.append(f"[0:a]atrim={s}:{e},asetpts=PTS-STARTPTS,afade=t=in:d=0.012,"
                  f"afade=t=out:st={max(0, e - s - 0.015):.3f}:d=0.015[a{i}];")
    n = len(segs)
    if speed != 1.0:   # прискорення мови: відео setpts, звук atempo (висота голосу не змінюється)
        fl.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vcat0][ab0];")
        fl.append(f"[vcat0]setpts=PTS/{speed}[vcat];[ab0]atempo={speed}[ab];")
    else:
        fl.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vcat][ab];")
    zi = zoom_intervals(ws_out, [[s / speed, e / speed] for s, e in segs], total)
    zsum = "+".join(f"between(on/{FPS}\\,{a:.3f}\\,{b - 0.001:.3f})" for a, b in zi) or "0"
    fl.append(f"[vcat]zoompan=z='1+{ZOOM - 1:.3f}*({zsum})':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"s={W}x{H}:fps={FPS},setsar=1[vb];")
    prev = "vb"
    inputs = [FF, "-y", "-i", src]
    idx = 1
    sfx = []
    for k, c in enumerate(cut_out):
        dur = round(c["end"] - c["start"], 3)
        inputs += ["-ss", str(c.get("ss", 0)), "-t", str(dur + 0.5), "-i", c["file"]]
        kb = (f"zoompan=z='min(1+0.10*on/({FPS}*{dur})\\,1.10)':d=1:x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}")
        fl.append(f"[{idx}:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"setsar=1,{kb},trim=duration={dur},setpts=PTS-STARTPTS+{c['start']}/TB[c{k}];")
        fl.append(f"[{prev}][c{k}]overlay=enable='between(t,{c['start']},{c['end']})':eof_action=pass[o{k}];")
        prev = f"o{k}"
        idx += 1
    fl.append(f"[{prev}]format=yuv420p,setsar=1[vout];")
    # music + whooshes
    music = cfg.get("music") or vm.MUSIC   # your own track: "music" in creatives.json or env VM_MUSIC
    m_idx = None
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        m_idx = idx; idx += 1
    if vm.WHOOSH:                              # your own whoosh: env VM_WHOOSH
        for k, c in enumerate(cut_out):
            inputs += ["-i", vm.WHOOSH]
            ms = max(0, int((c["start"] - 0.12) * 1000))
            fl.append(f"[{idx}:a]adelay={ms}:all=1,volume=0.22[w{k}];")
            sfx.append(f"[w{k}]")
            idx += 1
    if music:
        fl.append(f"[ab]loudnorm=I=-15:TP=-1.5:LRA=9,aresample=48000,asplit=2[voice][vkey];")
        fl.append(f"[{m_idx}:a]atrim=duration={total},asetpts=PTS-STARTPTS,aresample=48000,"
                  f"volume={cfg.get('music_vol', 0.16)},afade=t=in:d=0.6,afade=t=out:st={max(0, total - 1.2):.2f}:d=1.2[mraw];")
        fl.append("[mraw][vkey]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[mduck];")
        mix_in = "[voice][mduck]" + "".join(sfx)
        n_mix = 2 + len(sfx)
    else:
        fl.append(f"[ab]loudnorm=I=-15:TP=-1.5:LRA=9,aresample=48000[voice];")
        mix_in = "[voice]" + "".join(sfx)
        n_mix = 1 + len(sfx)
    if n_mix > 1:
        fl.append(f"{mix_in}amix=inputs={n_mix}:duration=first:normalize=0,alimiter=limit=0.95[aout]")
    else:
        fl.append("[voice]alimiter=limit=0.95[aout]")
    fc = PROJ / "work" / (cfg["name"] + "_fc.txt")
    fc.write_text("\n".join(fl), encoding="utf-8")
    cmd = inputs + [*vm.filter_script_args(fc), "-map", "[vout]", "-map", "[aout]",
                    "-r", str(FPS), "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
                    "-t", f"{total:.3f}", "-movflags", "+faststart", str(out_path)]
    run(cmd, log=PROJ / "work" / (cfg["name"] + "_comp.log"))


def render_final(comp, ass_path, out, fmt):
    vf = (f"crop={W}:{H45}:0:{Y45}," if fmt == "45" else "") + f"{vm.ass_filter(ass_path)},setsar=1,format=yuv420p"
    run([FF, "-y", "-i", str(comp), "-vf", vf, "-r", str(FPS), "-fps_mode", "cfr",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", str(out)],
        log=PROJ / "work" / (Path(out).stem + ".log"))


def main():
    allcfg = json.loads((PROJ / sys.argv[1]).read_text(encoding="utf-8"))
    names = [n for n in sys.argv[2:] if not n.startswith("--")]
    if names == ["all"]:
        names = [c["name"] for c in allcfg["creatives"]]
    known = [c["name"] for c in allcfg["creatives"]]
    bad = [n for n in names if n not in known]
    if bad or not names:
        sys.exit(f"Невідомі назви креативів: {bad or '(жодної не вказано)'}. Є в creatives.json: {known}")
    (PROJ / "work").mkdir(exist_ok=True)
    outdir = vm.DONE / date.today().isoformat() / vm.BRAND
    outdir.mkdir(parents=True, exist_ok=True)
    for cfg in allcfg["creatives"]:
        if cfg["name"] not in names:
            continue
        print(f"=== {cfg['name']}")
        src = PROJ / cfg["source"]
        src_dur = probe_dur(src)
        words = json.loads((PROJ / cfg["words"]).read_text(encoding="utf-8"))["words"]
        for t0, t1, text in cfg.get("inject", []):
            # phrase the transcriber missed: replace words in [t0,t1) with evenly spaced tokens
            toks = text.split()
            step = (t1 - t0) / len(toks)
            words = [w for w in words if not (t0 <= w["start"] < t1)] + [
                {"word": tk, "start": round(t0 + k * step, 3), "end": round(t0 + (k + 0.9) * step, 3)}
                for k, tk in enumerate(toks)]
            words.sort(key=lambda w: w["start"])
        exclude = cfg.get("exclude", [])
        ws, segs = build_segments(words, exclude, src_dur)
        ws = fix_words(ws, cfg.get("fixes", {}), cfg.get("fix_at", []))
        total_raw = round(sum(e - s for s, e in segs), 3)
        speed = pick_speed(cfg, len(ws), total_raw)
        total = round(total_raw / speed, 3)
        ws_out = [dict(w, start=src_to_out(w["start"], segs) / speed, end=src_to_out(w["end"], segs) / speed) for w in ws]
        cut_out = []
        for c in cfg.get("cutaways", []):
            a = src_to_out(c["at"], segs) / speed
            f = c["file"]
            if f.startswith("lib/"):   # lib/<category>/<clip without .mp4> -> <VM_ROOT>/library/...
                f = str(vm.LIBRARY / (f[4:] + ".mp4"))
            elif f.startswith("px/"):
                f = str(PROJ / "proxy" / (f[3:] + ".mp4"))
            if c.get("ss", 0) + c.get("dur", 1.6) > probe_dur(f):
                sys.exit(f"cutaway {f} too short for ss={c.get('ss', 0)} dur={c.get('dur', 1.6)}")
            cut_out.append({"start": round(a, 3), "end": round(min(a + c.get("dur", 1.6), total), 3),
                            "file": f, "ss": c.get("ss", 0)})
        print(f"  src {src_dur:.1f}s -> {total:.1f}s (speed x{speed}), {len(segs)} segments, {len(cut_out)} cutaways")
        (PROJ / "work" / (cfg["name"] + "_segments.json")).write_text(
            json.dumps({"segs": segs, "cutaways": cut_out, "words": ws_out}, ensure_ascii=False, indent=1), encoding="utf-8")
        comp = PROJ / "work" / (cfg["name"] + "_comp.mp4")
        if "--subs-only" not in sys.argv[2:] or not comp.exists():
            build_comp(cfg, segs, total, comp, cut_out, ws_out, speed)
        for fmt, label in (("916", "9x16"), ("45", "4x5")):
            ass = PROJ / "work" / f"{cfg['name']}_{fmt}.ass"
            ass.write_text(build_ass(ws_out, cfg, fmt, total), encoding="utf-8")
            render_final(comp, ass, outdir / f"{cfg['name']}_{label}.mp4", fmt)
        print(f"  done -> {outdir}")


if __name__ == "__main__":
    main()
