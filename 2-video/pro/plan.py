"""«Мозок» агента: з розшифровки робить монтажний лист (EDL).

Режим «мозку» (змінна середовища MONTAGE_BRAIN):
  agent (за замовчуванням) — завдання зберігається у work/<name>.plan_request.md, а монтажний лист (JSON за SCHEMA)
      складає ШІ-агент, який працює з користувачем, і кладе в work/<name>.edl.json. Далі run.py запускають знову.
  cli — рішення приймає `claude -p` (потрібен Claude Code CLI у PATH).

Використання: python plan.py <name> [--target 45] [--brief "…"] [--model opus]
Потрібні: work/<name>.words.txt (prepare.py)
Результат: work/<name>.edl.json
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from config import INPUT_BROLL, ROOT, WORK

SCHEMA = {
    "type": "object",
    "properties": {
        "keep": {"type": "array", "items": {"type": "array", "items": {"type": "integer"},
                                            "minItems": 2, "maxItems": 2}},
        "broll": {"type": "array", "items": {
            "type": "object",
            "properties": {"at_word": {"type": "integer"}, "to_word": {"type": "integer"},
                           "clip": {"type": "string"}, "dur": {"type": "number"},
                           "clip_start": {"type": "number"}},
            "required": ["at_word", "clip", "clip_start"]}},
        "emphasis": {"type": "array", "items": {"type": "integer"}},
        "word_fixes": {"type": "array", "items": {
            "type": "object",
            "properties": {"index": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["index", "text"]}},
        "overlays": {"type": "array", "items": {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": ["cta_arrows"]},
                           "from_word": {"type": "integer"}, "to_word": {"type": "integer"},
                           "broll_clip": {"type": "string"}, "broll_at_word": {"type": "integer"},
                           "clip_start": {"type": "number"}},
            "required": ["type", "from_word"]}},
        "music": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["keep", "broll", "overlays", "word_fixes", "notes"],
}


class BrainUnavailable(Exception):
    pass


def load_catalog() -> list[dict]:
    """Каталог перебивок: library/catalog.json (список записів або {"clips": [...]}). Запис: file, kind (video|photo),
    duration, description; необов'язково: sensitive, sensitive_reason, disabled, era (before|after: для платформи yt)."""
    path = INPUT_BROLL / "catalog.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    clips = data["clips"] if isinstance(data, dict) else data
    # без опису агент кадр не бачить; "disabled": true прибирає кадр; "sensitive" показується з позначкою «чутливе» (ставити лише за дозволом людини)
    return [c for c in clips if not c.get("disabled") and c.get("description")]


def era(file: str) -> str:
    """До чого належить кадр для правила YouTube: поле `era` каталогу (before|after) або нейтральний."""
    c = next((c for c in load_catalog() if c["file"] == file), None)
    return (c or {}).get("era", "neutral")


def broll_usage(exclude: str, days: int = 60) -> dict[str, list[str]]:
    """Які перебивки вже стоять в інших роликах: з монтажних листів у work/ за останні `days` днів.
    Окремого журналу не треба — кожен змонтований ролик лишає свій <name>.edl.json."""
    import time
    usage: dict[str, list[str]] = {}
    # work/history/ — монтажні листи з іншого комп'ютера (пакет для колеги): кадри з тих роликів теж не повторюємо
    for f in [*WORK.glob("*.edl.json"), *(WORK / "history").glob("*.edl.json")]:
        name = f.name.removesuffix(".edl.json")
        if name == exclude or "." in name or time.time() - f.stat().st_mtime > days * 86400:
            continue  # поточний ролик, резервні копії (*.manual, *.oldlib), старі
        try:
            edl = json.loads(f.read_text())
        except Exception:
            continue
        for b in edl.get("broll", []):
            usage.setdefault(b["clip"], [])
            if name not in usage[b["clip"]]:
                usage[b["clip"]].append(name)
    return usage


def build_prompt(name: str, target: float | None, brief: str | None, script: str | None = None,
                 platform: str = "meta", density: str = "normal") -> str:
    tr = json.loads((WORK / f"{name}.transcript.json").read_text())
    parts = [(ROOT / "prompts" / "edit.md").read_text()]
    catalog = load_catalog()
    if platform == "yt":  # YouTube: без оголених частин тіла
        catalog = [c for c in catalog if c.get("sensitive_reason") != "тіло"]
    usage = broll_usage(name)
    used = lambda c: (f", вже в {len(usage[c['file']])} рол.: {', '.join(usage[c['file']][:3])}"
                      if usage.get(c["file"]) else "")
    parts.append("## Каталог перебивок\n\n" + (
        "\n".join(f"- `{c['file']}` ({c.get('kind', 'video')}{', чутливе' if c.get('sensitive') else ''}, "
                  f"{c['duration']} с{used(c)}) — {c['description']}" for c in catalog)
        if catalog else "Каталог порожній — `broll` лишай порожнім."))
    from audio import tracks
    tl = tracks()
    if tl:
        parts.append("## Музика\n\nОдин трек на весь ролик (монтажер: посеред ролика не змінюється). Обери за настроєм "
                     "і темпом розповіді; трек коротший за ролик повториться по колу. Поле `music` — назва файлу.\n\n"
                     + "\n".join(f"- `{k}` — {v['mood']}, {v['duration']:.0f} с" for k, v in tl.items()))
    task = [f"## Завдання\n\nТривалість сирого матеріалу: {tr['duration']:.1f} с, мова: {tr['language']}."]
    if target:
        task.append(f"Цільова тривалість готового ролика: близько {target:.0f} с.")
    if platform == "yt":
        task.append("Платформа: YouTube. ЗАБОРОНЕНО показувати різницю «до» і «після» (не змішуй у ролику кадри "
                    "з позначкою era=before та era=after — обери один тип) і оголені частини тіла.")
    else:
        task.append("Платформа: Meta (обмеження YouTube не діють).")
    if density == "high":
        task.append("Щільність перебивок: ВИСОКА (історія про себе, «інтерес»). Перекривай кадрами щонайменше 60% "
                    "тривалості, міняй кадр кожні ~2–3 секунди, ілюструй образами навіть загальні фрази; "
                    "лиши чисту спікерку лише на кількох ключових фразах.")
    elif density == "low":
        task.append("Щільність перебивок: НИЗЬКА — лише там, де це необхідно (стики, докази).")
    if brief:
        task.append(f"Вказівки від замовника: {brief}")
    parts.append("\n".join(task))
    if script:
        parts.append("## Сценарій\n\n" + script.strip())
    parts.append("## Розшифровка\n\n" + (WORK / f"{name}.words.txt").read_text())
    parts.append("Поверни монтажний лист.")
    return "\n\n".join(parts)


def ask_claude_cli(prompt: str, model: str, schema: dict | None = None) -> dict:
    import os
    if os.environ.get("MONTAGE_BRAIN", "agent") != "cli":
        raise BrainUnavailable("режим «мозку» agent: монтажний лист складає ШІ-агент за plan_request.md")
    # ~/.local/bin часто немає в PATH термінала — перевіряємо стандартне місце встановлення
    local = Path.home() / ".local" / "bin" / "claude"
    exe = shutil.which("claude") or (str(local) if local.exists() else None)
    if not exe:
        raise BrainUnavailable("CLI `claude` не знайдено (ні в PATH, ні в ~/.local/bin)")
    r = subprocess.run(
        [exe, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
         "--model", model, "--json-schema", json.dumps(schema or SCHEMA)],
        input=prompt, capture_output=True, text=True, timeout=600)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise BrainUnavailable(f"CLI повернув не JSON: {(r.stdout or r.stderr)[:300]}")
    if out.get("is_error"):
        raise BrainUnavailable(str(out.get("result"))[:300])
    edl = out.get("structured_output")
    if edl is None:  # старіші версії CLI кладуть JSON текстом у result
        edl = json.loads(out["result"])
    return edl


def validate(edl: dict, n_words: int, platform: str = "meta") -> list[str]:
    """Перевіряє і нормалізує монтажний лист на місці. Повертає список попереджень."""
    warn = []
    keep, prev = [], -1
    for a, b in sorted(edl.get("keep", [])):
        if not (0 <= a <= b < n_words):
            warn.append(f"keep [{a},{b}] поза межами 0..{n_words - 1} — пропущено")
            continue
        if a <= prev:
            warn.append(f"keep [{a},{b}] перетинається з попереднім — обрізано")
            a = prev + 1
            if a > b:
                continue
        keep.append([a, b])
        prev = b
    edl["keep"] = keep
    kept = {i for a, b in keep for i in range(a, b + 1)}

    catalog = load_catalog()
    kinds = {c["file"]: c.get("kind", "video") for c in catalog}
    # фото можна тримати скільки треба (вони з Ken Burns), відео — не довше за сам кліп
    clips = {c["file"]: (12.0 if c.get("kind") == "photo" else c["duration"]) for c in catalog}
    broll = []
    for b in edl.get("broll", []):
        if b["clip"] not in clips:
            warn.append(f"перебивка {b['clip']}: немає в каталозі — пропущено")
        elif b["at_word"] not in kept:
            warn.append(f"перебивка {b['clip']}: слово {b['at_word']} не збережене — пропущено")
        else:
            cap = clips[b["clip"]]
            b["clip_start"] = 0.0 if kinds[b["clip"]] == "photo" else max(0.0, min(b.get("clip_start", 0.0), cap - 0.5))
            b["max_dur"] = round(cap - b["clip_start"], 2)
            if b.get("to_word") is not None and (b["to_word"] not in kept or b["to_word"] < b["at_word"]):
                warn.append(f"перебивка {b['clip']}: to_word {b['to_word']} некоректний — використано dur")
                b.pop("to_word")
            b["dur"] = round(max(0.5, min(b.get("dur") or 2.5, b["max_dur"])), 2)
            broll.append(b)
    edl["broll"] = sorted(broll, key=lambda b: b["at_word"])
    if platform == "yt":  # правило YouTube: не показувати різницю «до» і «після»
        used = [b["clip"] for b in edl["broll"]] + [o["broll_clip"] for o in edl.get("overlays", []) if o.get("broll_clip")]
        eras = {era(f) for f in used}
        if "before" in eras and "after" in eras:
            warn.append("YouTube: у ролику були кадри і «до», і «після» — кадри «після» прибрано")
            edl["broll"] = [b for b in edl["broll"] if era(b["clip"]) != "after"]
            for o in edl.get("overlays", []):
                if o.get("broll_clip") and era(o["broll_clip"]) == "after":
                    for k in ("broll_clip", "broll_at_word", "clip_start"):
                        o.pop(k, None)
        banned = {c["file"] for c in load_catalog() if c.get("sensitive_reason") == "тіло"}
        edl["broll"] = [b for b in edl["broll"] if b["clip"] not in banned]

    overlays = []
    for o in edl.get("overlays", []):
        t = o.get("type")
        if o.get("from_word") not in kept:
            warn.append(f"накладка {t}: слово {o.get('from_word')} не збережене — пропущено")
            continue
        if t == "cta_arrows":
            if any(x["type"] == "cta_arrows" for x in overlays):
                warn.append("другі стрілки CTA — пропущено")
                continue
            if o.get("to_word") not in kept or o["to_word"] <= o["from_word"]:  # to_word — стрілки лише до цього слова
                o.pop("to_word", None)
        else:
            warn.append(f"невідомий тип накладки {t} — пропущено")
            continue
        overlays.append(o)
    edl["overlays"] = overlays

    if edl.get("music"):
        from audio import tracks
        if edl["music"] not in tracks():
            warn.append(f"музика {edl['music']!r}: немає серед треків (input/audio/music/tracks.json) — без музики")
            edl["music"] = ""

    emph = sorted({i for i in edl.get("emphasis", []) if i in kept})
    edl["emphasis"] = emph[: max(1, len(kept) // 6)] if emph else []

    fixes = edl.get("word_fixes", {})
    if isinstance(fixes, list):
        fixes = {str(f["index"]): f["text"] for f in fixes}
    # порожній рядок = сховати слово в субтитрах (другий шматок розірваного слова)
    edl["word_fixes"] = {k: v.strip() for k, v in fixes.items() if k.isdigit() and int(k) < n_words}

    if not keep:
        warn.append("монтажний лист порожній: немає keep")
    return warn


SMALL_EXTRA = {"і", "й", "а", "ну", "е", "е-е", "ее", "м", "м-м", "мм", "хм", "ем", "от", "ось", "так", "то",
               "він", "вона", "вони", "воно", "вот", "и", "ну-у", "ага"}


def _norm(t: str) -> str:
    import re
    t = re.sub(r"\s+(['-])", r"\1", t.lower().replace("’", "'"))
    return re.sub(r"[^\w'-]", "", t)


def trim_to_script(edl: dict, words: list[dict], script: str) -> list[str]:
    """Звірка keep зі сценарієм слово в слово. Короткі вставки, яких у сценарії немає (вигуки «і…», «ну»,
    «він», повтор-фальстарт «потім… потім»), вирізає сама — «мозок» їх іноді пропускає («бунтувати і, ну,
    з його»). Довші розбіжності лише повідомляє. Посилання перебивок/накладок переносить на наступне слово."""
    import difflib
    kept = [i for a, b in edl["keep"] for i in range(a, b + 1)]
    ref = [w for w in (_norm(x) for x in script.split()) if w]
    got = [_norm(words[i]["w"]) for i in kept]
    drop, notes = set(), []
    sm = difflib.SequenceMatcher(a=ref, b=got, autojunk=False)
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op != "insert":
            continue
        run = got[b0:b1]
        nxt = ref[a0] if a0 < len(ref) else ""
        if len(run) <= 2 and all(w in SMALL_EXTRA or w == nxt or not w for w in run):
            drop.update(kept[b0:b1])
        elif len(run) <= 6:
            notes.append(f"поза сценарієм лишилось: «{' '.join(words[i]['w'] for i in kept[b0:b1])}»")
    if not drop:
        return notes
    left = [i for i in kept if i not in drop]
    keep = []
    for i in left:
        if keep and i == keep[-1][1] + 1:
            keep[-1][1] = i
        else:
            keep.append([i, i])
    edl["keep"] = keep
    nxt_kept = lambda i: next((j for j in left if j >= i), left[-1])
    for b in edl.get("broll", []):
        b["at_word"] = nxt_kept(b["at_word"])
        if b.get("to_word") is not None:
            b["to_word"] = max(b["at_word"], nxt_kept(b["to_word"]))
    for o in edl.get("overlays", []):
        for k in ("from_word", "to_word", "broll_at_word"):
            if o.get(k) is not None:
                o[k] = nxt_kept(o[k])
    edl["emphasis"] = sorted({nxt_kept(i) for i in edl.get("emphasis", [])})
    notes.insert(0, "вирізано поза сценарієм: " + ", ".join(f"«{words[i]['w']}»" for i in sorted(drop)))
    return notes


def n_words(name: str) -> int:
    tr = json.loads((WORK / f"{name}.transcript.json").read_text())
    return sum(len(s["words"]) for s in tr["segments"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--target", type=float, default=None, help="цільова тривалість, с")
    ap.add_argument("--brief", default=None, help="вказівки для монтажу вільним текстом")
    ap.add_argument("--script", type=Path, default=None, help="файл зі сценарієм (еталон тексту)")
    ap.add_argument("--platform", default="meta", choices=["meta", "yt"], help="yt = заборона «до/після» і тіла")
    ap.add_argument("--density", default="normal", choices=["low", "normal", "high"])
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()

    prompt = build_prompt(a.name, a.target, a.brief, a.script.read_text() if a.script else None, a.platform, a.density)
    edl_path = WORK / f"{a.name}.edl.json"
    try:
        edl = ask_claude_cli(prompt, a.model)
    except (BrainUnavailable, subprocess.TimeoutExpired) as e:
        req = WORK / f"{a.name}.plan_request.md"
        req.write_text(prompt)
        print(f"▸ {e}\n"
              f"  Завдання збережено: {req}\n"
              f"  Агенте: прочитай його, склади монтажний лист (JSON за SCHEMA у plan.py) і збережи в {edl_path}; потім запусти run.py знову.")
        sys.exit(2)

    for w in validate(edl, n_words(a.name), a.platform):
        print("  увага:", w)
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=1))
    print(f"монтажний лист: шматків {len(edl['keep'])}, "
          f"перебивок {len(edl['broll'])}, накладок {len(edl['overlays'])}, виправлень {len(edl['word_fixes'])}\n  {edl['notes']}\n→ {edl_path}")
