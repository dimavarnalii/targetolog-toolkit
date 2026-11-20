"""Звук: чистка шуму, нормалізація гучності, ефекти на вставках, музика.

За відповідями монтажера:
- «нормалізація гучності» на всьому відео й «чистка шумів» — стандартні налаштування;
- усі вставки (картинки, скріни, коментарі) виводяться зі звуковим ефектом, ефекти −20…−30 дБ;
- музика зі стоків без авторських прав, зазвичай альтернативний хіп-хоп, гучність −30 дБ.
Музика й ефекти — від монтажера (06.10): input/audio/music (+ tracks.json: настрій, гучність, «щільність»
мовного діапазону → наскільки тихіше під голос), templates/sfx/<подія>_<n>.wav (+ sfx.json). Монтажер:
музика −25…−35 дБ «залежно від спікера і треку — треба слухати», не змінюється посеред ролика; звук — під
кожну вставку. Тому гучність музики адаптивна (щільніший трек — тихіше) і під голосом вона ще й притихає.
"""
import subprocess
from pathlib import Path

from config import DATA, FFMPEG, ROOT

SFX_DIR = DATA / "sfx"   # свої звуки: <подія>_<n>.wav; якщо немає, синтезуються прості
MUSIC_DIR = DATA / "input" / "audio" / "music"   # ваша музика (в пакеті її немає)

VOICE_LUFS = -16          # цільова гучність голосу
SFX_BELOW = 12            # ефекти нижче голосу, LU
MUSIC_BELOW = 22          # музика нижче голосу, LU, якщо для треку немає заміру в tracks.json

VOICE_CHAIN = ("highpass=f=70,afftdn=nr=10:nf=-40,"
               f"loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=11,aresample=48000")


def _make(name: str, args: list[str]) -> Path:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    dst = SFX_DIR / f"{name}.wav"
    if not dst.exists():
        subprocess.run([FFMPEG, "-loglevel", "error", "-y", *args, str(dst)], check=True)
    return dst


def sfx_file(kind: str, n: int = 0) -> Path:
    """Файл монтажера templates/sfx/<kind>_<номер>.wav|mp3 (кілька варіантів — по черзі, щоб не було
    монотонно: «клік», «клік 2», «кнопка»), інакше синтезований."""
    import re
    real = sorted(p for p in SFX_DIR.glob(f"{kind}_*") if re.fullmatch(rf"{kind}_\d+\.(wav|mp3)", p.name)) \
        if SFX_DIR.exists() else []
    if real:
        return real[n % len(real)]
    if kind == "pop":
        return _make("pop", ["-f", "lavfi", "-i",
                             "aevalsrc='0.9*sin(2*PI*(900*t-3000*t*t))*exp(-25*t)':d=0.2:s=48000"])
    return _make("whoosh", ["-f", "lavfi", "-i", "anoisesrc=d=0.8:c=pink:r=48000:a=0.7",
                            "-af", "highpass=f=400,lowpass=f=7000,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.5"])


def tracks() -> dict:
    import json
    f = MUSIC_DIR / "tracks.json"
    return json.loads(f.read_text()) if f.exists() else {}


def pick_music(arg: str | None) -> Path | None:
    """Файл, назва треку з бібліотеки (вибір «мозку») або auto (перший нейтральний)."""
    if not arg or arg == "none":
        return None
    if (MUSIC_DIR / arg).exists():
        return MUSIC_DIR / arg
    if arg != "auto":
        return Path(arg)
    files = sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a")) if MUSIC_DIR.exists() else []
    neutral = [p for p in files if p.name.startswith("neutral")]
    return (neutral or files or [None])[0]


def music_gap(music: Path, override: float | None = None) -> float:
    """Наскільки тихіше за голос: заміряно для треку (щільніший мовний діапазон — тихіше), або вручну."""
    if override is not None:
        return override
    return float(tracks().get(music.name, {}).get("gap", MUSIC_BELOW))


def music_filters(filters: list, idx: int, voice: str, duration: float, music: Path, gap: float | None = None) -> str:
    """Фільтри музики: рівень під голосом (адаптивний), плавні вхід/вихід, притишення під час мовлення
    (sidechain від голосу: −3…−6 дБ, коли говорять, у паузах повертається). Повертає мітку музики."""
    g = music_gap(music, gap)
    filters.append(f"[{idx}:a]atrim=0:{duration:.2f},asetpts=PTS-STARTPTS,"
                   f"loudnorm=I={VOICE_LUFS - g:.1f}:TP=-3:LRA=7,aresample=48000,"
                   f"afade=t=in:d=0.8,afade=t=out:st={max(0, duration - 1.5):.2f}:d=1.5[musraw]")
    filters.append(f"[musraw]{voice}sidechaincompress=threshold=0.05:ratio=2:attack=80:release=600:makeup=1[mus]")
    return "[mus]"


def events_from_cut(cut: dict) -> list[tuple[float, str]]:
    ev = [(b["start"], "pop") for b in cut.get("broll", [])]
    for o in cut.get("overlays", []):
        ev.append((o["start"], "pop"))
    return sorted(ev)


def render_audio(src: str, events: list, duration: float, music: Path | None, dst: Path,
                 gap: float | None = None) -> None:
    """Окремий прохід по звуку (дешево): чистка + нормалізація голосу, ефекти на вставках, музика → m4a.
    Окремо від відео, бо в одному великому графі з десятком входів ffmpeg міг зависати."""
    inputs, filters = ["-i", src], []
    aout = add_audio(inputs, filters, events, duration, music, gap=gap)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(filters),
                    "-map", aout, "-vn", "-c:a", "aac", "-b:a", "192k", str(dst)], check=True)


def add_audio(inputs: list, filters: list, events: list, duration: float,
              music: Path | None = None, voice_label: str = "0:a", gap: float | None = None,
              clean_voice: bool = True) -> str:
    """Дописує вхідні файли й фільтри; повертає мітку змішаного звуку. Лічильник входів — за кількістю «-i».
    events: (час, подія) або (час, подія, макс. тривалість) — довгий «вжух» обрізається під хук."""
    filters.append(f"[{voice_label}]{VOICE_CHAIN if clean_voice else 'anull'},asplit=2[voice][vsc]")
    labels = ["[voice]"]
    seen: dict[str, int] = {}
    for n, ev in enumerate(events):
        t, kind = ev[0], ev[1]
        cap = ev[2] if len(ev) > 2 else None
        idx = inputs.count("-i")
        inputs += ["-i", str(sfx_file(kind, seen.get(kind, 0)))]
        seen[kind] = seen.get(kind, 0) + 1
        ms = max(0, int(t * 1000) - 30)
        trim = f"atrim=0:{cap:.2f},afade=t=out:st={max(0, cap - 0.3):.2f}:d=0.3," if cap else ""
        filters.append(f"[{idx}:a]{trim}aresample=48000,adelay={ms}|{ms},volume=-{SFX_BELOW}dB[sf{n}]")
        labels.append(f"[sf{n}]")
    if music:
        idx = inputs.count("-i")
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        labels.append(music_filters(filters, idx, "[vsc]", duration, music, gap))
    else:
        filters.append("[vsc]anullsink")
    # обмежувач із запасом: −2 дБ на вибірках → після стиснення AAC справжній пік ≤ −1 dBTP (вимога; qa.py
    # на 0,95 показав −0,5 dBTP — гучні склади могли хрипіти на телефонах)
    limiter = "alimiter=limit=0.79:attack=5:release=50:level=disabled"
    if len(labels) == 1:
        filters.append(f"[voice]{limiter}[aout]")
    else:
        filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,{limiter}[aout]")
    return "[aout]"
