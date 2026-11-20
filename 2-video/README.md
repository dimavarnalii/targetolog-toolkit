# Пакет «Монтаж рекламних відеокреативів» (Модуль 2)

Скрипти на Python + ffmpeg + faster-whisper. Усе працює на вашому комп'ютері, жодних акаунтів і токенів не потрібно.
Музики, звуків, відеокліпів, банерів і шрифтів у пакеті НЕМАЄ — ви підставляєте свої (з правами на використання).

## Що всередині

```
SKILL.md                    скіл для Claude Code (вставте у .claude/skills/ad-montage/SKILL.md)
scripts/                    спільні скрипти
  vm_config.py                налаштування (змінні середовища) + перевірка ffmpeg/faster-whisper
  transcribe_words.py         транскрипт зі словами й таймкодами
  repeats.py                  перевірка дублів тексту (звук і стики субтитрів)
  cut_phrase.py               вирізати фразу з готового ролика (межі по зміні кадру)
  burn_subs.py                субтитри на готове відео
  verify_video.py             перевірка файлу на «чорний екран» (moov, fps, SAR, піксельний формат, декод)
  scan_sheet.py               кадри з координатною сіткою (для кропів у шортсах)
  yt_fetch.py / shorts.py / render_project.py / build_dynamic_ass.py / build_overlay_filter.py /
  build_zoom_filter.py / build_outro.py / slice_words.py / build_library_manifest.py   режим шортсів
  avatar_audio.py / words_to_captions.py   допоміжні для режиму аватара (Remotion)
ad_creatives/               основний режим: креативи із сирих дублів
  make_proxies.py  transcribe_medium.py  gapcheck.py  tl_inspect.py  findw.py  broll_sheet.py  build_creative.py
  creatives.example.json
references/                 ad_creatives.md, editing_rules.md, pitfalls.md, shorts.md, avatar_remotion.md
library_example/            як скласти свою бібліотеку перебивок (README + manifest.example.json)
remotion_avatar/            необов'язково: Remotion-шаблон для ролика з AI-аватаром (потрібен Node.js)
```

## Встановлення (один раз)

1. Python 3.10+.
2. `pip install faster-whisper numpy` (для YouTube-завантаження шортсів ще `pip install yt-dlp`).
3. ffmpeg + ffprobe: офіційна збірка для вашої ОС, додати в PATH (або задати `VM_FFMPEG`/`VM_FFPROBE`).
4. Шрифт для субтитрів: за замовчуванням ASS-стиль просить «Arial Black» (Windows/macOS). Інакше встановіть будь-який жирний шрифт з потрібною абеткою
   і задайте `VM_ASS_FONT="Назва шрифта"` (за потреби `VM_FONTS_DIR` — папка з .ttf).
   Приклад вільного шрифта: Montserrat (Google Fonts, ліцензія SIL OFL) — завантажте з fonts.google.com самі.
5. Змінні середовища (див. `scripts/vm_config.py`). Мінімум — нічого, якщо ffmpeg у PATH.
   Приклади: PowerShell `$env:VM_ROOT="D:\work\ads"; $env:VM_MUSIC="D:\music\track.mp3"; $env:PYTHONIOENCODING="utf-8"`;
   bash `export VM_ROOT=~/ads VM_MUSIC=~/music/track.mp3`.
6. Перевірка: `python scripts/vm_config.py` (код 0 = все гаразд).

## Папки

`<VM_ROOT>/sources` (сирі та завантажені джерела), `projects/<назва>` (робота над проєктом), `done/<дата>` (результат), `library` (ваші перебивки).
Скрипти `ad_creatives/*` запускають з папки проєкту: `cd <VM_ROOT>/projects/<назва>`.

## Швидкий старт (креативи)

```
cd <VM_ROOT>/projects/my_ad
python <пакет>/ad_creatives/make_proxies.py <папка_із_сирими>
python <пакет>/ad_creatives/transcribe_medium.py --lang uk IMG_0001
python <пакет>/ad_creatives/tl_inspect.py IMG_0001
# напишіть creatives.json за зразком ad_creatives/creatives.example.json
python <пакет>/ad_creatives/build_creative.py creatives.json K1_example
python <пакет>/scripts/verify_video.py <VM_ROOT>/done/<дата>/creatives/K1_example_9x16.mp4 --fps 30
```
Повний опис — `references/ad_creatives.md`.

## Стан перевірки

Пакет перевірено чистим агентом (лише за PDF) на синтетичному кліпі та автором на реальному відео українською (50 с, 720x1280): проксі, транскрипт, креатив 9:16 і 4:5, перевірка файлів. Не перевірено: музика, бібліотека перебивок, ffmpeg старше 7, режими shorts і avatar.
