"""Pro-монтаж: весь пайплайн однією командою, сире відео → готові креативи.

  python run.py <відео> --lang uk --style box

Кроки: розшифровка → паузи → монтажний лист («мозок») → склейка → трекінг обличчя →
рендер форматів (+ окремі хуки, якщо в сирому матеріалі дублі хука).
Кожен крок кешується у work/: повторний запуск продовжує з місця зупинки.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from config import OUTPUT, ROOT, WORK, out_find
from plan import n_words, validate

NOISE = ("objc[", "HF Hub", "WARN:", "setPreferableTarget")


def step(title: str, script: str, *args: str, ok_codes=(0,)) -> int:
    """Кожен крок — окремий процес: PyAV (whisper) і OpenCV не можна вантажити разом."""
    print(f"\n▸ {title}", flush=True)
    t0 = time.time()
    p = subprocess.Popen([sys.executable, str(ROOT / script), *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in p.stdout:
        if not any(n in line for n in NOISE):
            print("  " + line.rstrip(), flush=True)
    code = p.wait()
    if code not in ok_codes:
        sys.exit(f"✗ крок «{title}» завершився з кодом {code}")
    print(f"  ({time.time() - t0:.0f} с)")
    return code


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path, help="сирий відеофайл")
    ap.add_argument("--lang", default=None, help="uk / ru / en; без параметра — автовизначення")
    ap.add_argument("--style", default="box", help="стиль субтитрів: box (плашка) | pyshka (дрібний білий капс на рівні грудей) | reels (лише FFmpeg-рендер)")
    ap.add_argument("--formats", default="9x16,4x5")
    ap.add_argument("--target", type=float, default=None, help="цільова тривалість ролика, с")
    ap.add_argument("--brief", default=None, help="вказівки для монтажу вільним текстом")
    ap.add_argument("--speed", default="auto",
                    help="прискорення мови: число (1.1 = +10%%) або auto — підганяє темп до ~3 слів/с, не більше +25%%")
    ap.add_argument("--pause", type=float, default=None,
                    help="до скількох секунд скорочувати паузи між фразами (0.4; для AI-аватара/TTS став 3: паузи не різати)")
    ap.add_argument("--density", default="normal", choices=["low", "normal", "high"],
                    help="щільність перебивок; high — для історії про себе («інтерес»)")
    ap.add_argument("--script", type=Path, default=None, help="файл зі сценарієм: еталон тексту, хуки, терміни")
    ap.add_argument("--platform", default="meta", choices=["meta", "yt"],
                    help="yt: не змішувати кадри «до» і «після» (поле era у каталозі) і без кадрів із sensitive_reason=тіло")
    ap.add_argument("--music", default="plan", help="музика: plan — трек, який обрав «мозок» (за замовч.); назва треку чи "
                                                    "файл; auto — перший нейтральний; none — без музики")
    ap.add_argument("--music-gap", type=float, default=None, help="наскільки музика тихіша за голос, LU (за замовч. — "
                                                                 "заміряно для треку: 20–28)")
    ap.add_argument("--name", default=None, help="назва креативу для файлів готового ролика (її дає замовник): <name>[_hN]_<9x16|4x5>.mp4")
    ap.add_argument("--renderer", default="remotion", choices=["remotion", "ffmpeg"],
                    help="remotion — анімоване оформлення (за замовчуванням); ffmpeg — старий швидкий рендер")
    ap.add_argument("--box-color", default="#325C3C", help="колір плашки субтитрів для стилю box (під палітру ролика)")
    ap.add_argument("--hook-src", default=None, help="файл із хуком-питанням (напр. запис інтервʼюера)")
    ap.add_argument("--hook-in", type=float, default=0.0)
    ap.add_argument("--hook-out", type=float, default=0.0)
    ap.add_argument("--hook-title", default=None, help="текст плашки на хуку-питанні")
    ap.add_argument("--model", default="opus", help="модель «мозку»")
    ap.add_argument("--replan", action="store_true", help="перескласти монтажний лист")
    ap.add_argument("--fresh", action="store_true", help="ігнорувати кеш, почати з розшифровки")
    ap.add_argument("--preview", default=None, choices=["cut", "fast"],
                    help="перевірка правок без повного рендеру: cut — лише склейка зі звуком (~1 хв), "
                         "fast — повне оформлення в половинній роздільності, перший формат (~4× швидше)")
    a = ap.parse_args()

    video = a.video.resolve()
    if a.lang:
        os.environ["MONTAGE_LANG"] = a.lang   # діє на всі кроки (синхронізація, перевірка, автовиправлення)
    from config import FACE_MODEL, WHISPER_DIR
    if not any(WHISPER_DIR.glob("models--*/snapshots/*/model.bin")) and not os.environ.get("MONTAGE_ALLOW_DOWNLOAD"):
        sys.exit(f"✗ Немає моделі Whisper в {WHISPER_DIR}. Спершу (після згоди користувача): python fetch_models.py whisper --yes")
    if not FACE_MODEL.exists():
        sys.exit(f"✗ Немає моделі обличчя {FACE_MODEL}. Спершу (після згоди користувача): python fetch_models.py yunet --yes")
    if a.pause is None:
        a.pause = 0.4
    if not video.exists():
        sys.exit(f"✗ файл не знайдено: {video}")
    name = video.stem
    t_start = time.time()
    WORK.mkdir(exist_ok=True)
    transcript, edl_path = WORK / f"{name}.transcript.json", WORK / f"{name}.edl.json"

    if a.fresh or not transcript.exists():
        step("Розшифровка", "transcribe.py", str(video), *(["--lang", a.lang] if a.lang else []))
    else:
        print(f"\n▸ Розшифровка — з кешу ({transcript.name})")
    if not json.loads(transcript.read_text()).get("aligned"):  # точні межі слів (окремий процес: torch)
        import importlib.util
        if os.environ.get("MONTAGE_ALIGN") != "1" or importlib.util.find_spec("torch") is None:
            print("\n▸ Точні межі слів: пропущено; межі слів від Whisper (трохи менш точні). Вмикається MONTAGE_ALIGN=1 "
                  "(потрібні torch, torchaudio, uroman; ваги MMS мають некомерційну ліцензію CC-BY-NC: перевір, чи вони підходять для клієнтської роботи)")
        else:
            step("Точні межі слів (вирівнювання MMS)", "align.py", str(transcript))
    step("Паузи і нумерація слів", "prepare.py", str(transcript))

    if a.fresh or a.replan or not edl_path.exists():
        extra = ((["--target", str(a.target)] if a.target else []) + (["--brief", a.brief] if a.brief else [])
                 + (["--script", str(a.script.resolve())] if a.script else [])
                 + ["--platform", a.platform, "--density", a.density])
        if step("Монтажний лист", "plan.py", name, "--model", a.model, *extra, ok_codes=(0, 2)) == 2:
            sys.exit(2)
    else:
        print(f"\n▸ Монтажний лист — з кешу ({edl_path.name}); --replan, щоб перескласти")

    edl = json.loads(edl_path.read_text())
    edl.setdefault("overlays", [])
    for w in validate(edl, n_words(name), a.platform):
        print("  увага:", w)
    if edl.get("broll"):  # різноманітність: скільки кадрів уже були в інших роликах
        from plan import broll_usage
        usage = broll_usage(name)
        rep = [b["clip"] for b in edl["broll"] if usage.get(b["clip"])]
        print(f"  перебивки: {len(edl['broll'])}, з них уже були в інших роликах: {len(rep)}"
              + (f" ({', '.join(rep)})" if rep else ""))
    if a.script and edl.get("keep"):  # звірка зі сценарієм: зайві «і», «ну», фальстарти — вирізати автоматично
        from plan import trim_to_script
        tr_words = [w for s in json.loads(transcript.read_text())["segments"] for w in s["words"]]
        for msg in trim_to_script(edl, tr_words, a.script.read_text()):
            print("  звірка зі сценарієм:", msg)
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=1))

    outputs = []
    speed = a.speed
    if edl["keep"] and str(speed) == "auto":
        # темп мови: слів на секунду чистої мови в збережених шматках → підганяємо до ~3 слів/с (виміряно у 4.1)
        tr = json.loads(transcript.read_text())
        words = [w for s in tr["segments"] for w in s["words"]]
        kept = [words[i] for x, y in edl["keep"] for i in range(x, y + 1)]
        # тривалість слів — за межами Whisper: на них відкалібровано 3 слова/с; межі вирівнювання щільніші
        # (лише звучання), з ними темп «виходив» 3,5 слова/с і прискорення не вмикалось
        dur = lambda w: (w["whisper"][1] - w["whisper"][0]) if "whisper" in w else (w["end"] - w["start"])
        rate = len(kept) / max(1e-6, sum(dur(w) for w in kept))
        speed = round(min(1.25, max(1.0, 3.0 / rate)), 2)
        print(f"\n▸ Темп мови {rate:.2f} слів/с → прискорення ×{speed}")
    use_rm = a.renderer == "remotion" and a.style in ("box", "pyshka")
    if a.renderer == "remotion" and not use_rm:
        print(f"  увага: стиль {a.style} є лише у FFmpeg-рендері — рендерю через FFmpeg")
    fmts = a.formats.split(",")
    if edl["keep"]:
        # auto: своє прискорення для кожного шматка (cut.piece_speeds), число — однакове для всіх
        step("Склейка", "cut.py", str(edl_path), "auto" if str(a.speed) == "auto" else str(speed), str(a.pause))
        if a.script:  # повторне розпізнавання склейки: зайві «і», фальстарти, обрізані слова
            step("Перевірка склейки на слух (порівняння зі сценарієм)", "verify.py", name, str(a.script.resolve()))
        # зайві вигуки й фальстарти: почуті перевіркою (зі сценарієм) і «сховані» Whisper між сусідніми словами
        # (працює й без сценарію) — вирізати, перескласти й перевірити ще раз (один повтор, без зациклення)
        if step("Автовиправлення зайвих вигуків і фальстартів", "autofix.py", name,
                *([] if a.script else ["--no-verify"]), ok_codes=(0, 1)) == 0:
            step("Склейка (після автовиправлення)", "cut.py", str(edl_path),
                 "auto" if str(a.speed) == "auto" else str(speed), str(a.pause))
            if a.script:
                step("Повторна перевірка на слух", "verify.py", name, str(a.script.resolve()))
        # остання перевірка: субтитри й перебивки під реальний звук (де вирівнювання помилилось на ділянці)
        step("Синхрон субтитрів зі звуком", "sync.py", name)
        vsuf = ""
        hook_args = (["--hook-src", str(Path(a.hook_src).resolve()), "--hook-in", str(a.hook_in), "--hook-out", str(a.hook_out)]
                     if a.hook_src else []) + (["--hook-title", a.hook_title] if a.hook_title else [])
        if a.preview:  # чернетка для перевірки: фінальні файли не перезаписуємо
            f = fmts[0]
            out = OUTPUT / f"{name}_preview_{a.preview}{'' if a.preview == 'cut' else '_' + f}.mp4"
            extra = ["--master-only", str(out)] if a.preview == "cut" else ["--scale", "0.5", "--render", str(out)]
            step(f"Чернетка ({a.preview})", "to_remotion.py", name, "--fmt", f, "--style", a.style,
                 "--box-color", a.box_color, *hook_args, *extra)
            print(f"\n✓ Чернетка за {time.time() - t_start:.0f} с: {out}")
            sys.exit(0)
        # музика: трек, який обрав «мозок» (або заданий вручну); один на весь ролик — тож при «хук + тіло»
        # накладається в склейці, а тіло рендериться без неї
        music_arg = edl.get("music") if a.music == "plan" else (None if a.music == "none" else a.music)
        if music_arg:
            print(f"  музика: {music_arg}" + (f" (тихіше за голос на {a.music_gap} LU)" if a.music_gap else ""))
        body_music = music_arg
        mus_args = (["--music", body_music] if body_music else []) + \
                   (["--music-gap", str(a.music_gap)] if body_music and a.music_gap is not None else [])
        if use_rm:
            for f in fmts:
                step(f"Рендер {f} (Remotion)", "to_remotion.py", name, "--fmt", f, "--style", a.style,
                     "--box-color", a.box_color, *hook_args, *mus_args,
                     "--render", str(OUTPUT / f"{name}{vsuf}_{f}.mp4"))
        else:
            step("Трекінг обличчя", "track.py", str(WORK / f"{name}.master.mp4"))
            step("Рендер форматів", "render.py", name, "--style", a.style, "--formats", a.formats,
                 *(["--music", body_music] if body_music else []))
        outputs += [OUTPUT / f"{name}{vsuf if use_rm else ''}_{f}.mp4" for f in fmts]
    if a.name:  # назва від замовника: <name>[_hN]_<формат>.mp4
        named = []
        for o in outputs:
            m = re.match(rf"{re.escape(name)}(?:_full)?(?:_v(?:split|text))?(?:_(h\d+))?_(9x16|4x5)\.mp4$", o.name)
            if m:
                dst = OUTPUT / f"{a.name}{'_' + m.group(1) if m.group(1) else ''}_{m.group(2)}.mp4"
                shutil.copy2(o, dst)
                named.append(dst)
        outputs = named or outputs

    # контроль якості кожного готового файлу: гучність, пік, бітрейт, Rec.709, чорні/застиглі кадри, тиша
    if outputs:
        step("Контроль якості", "qa.py", *[str(o) for o in outputs], ok_codes=(0, 1))
    print(f"\n✓ Готово за {time.time() - t_start:.0f} с. Файли:")
    for o in outputs:
        print("  ", o)
    if edl.get("notes"):
        print("\nНотатки монтажера:", edl["notes"])
