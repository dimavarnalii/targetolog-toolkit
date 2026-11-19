# Відомі проблеми і що з ними робити

| Симптом | Причина | Рішення |
|---|---|---|
| У користувача чорний екран, звук є | moov atom в кінці файлу | `-movflags +faststart` (або ремукс `-c copy -movflags +faststart`) |
| Те саме, після перебивок | перебивки з різним fps (24/25/30) | нормалізувати `fps=25` у кожній гілці, вихід `-r 25 -fps_mode cfr` |
| Те саме, після кропу/спліту | SAR ≠ 1:1 (кадр «стиснутий» метаданими) | `setsar=1` в кінці кожної гілки і після concat |
| Рендер «біжить» за тривалість, файл величезний | зациклена картинка (`-loop 1`) без `-t` | `-t <total_duration>` на input картинки |
| Тривалість результату більша за очікувану | довгий input (музика, кліп) без обрізки | `-t`/`trim` по тривалості основи |
| `UnicodeEncodeError` / кракозябри | Python у Windows-консолі | `PYTHONIOENCODING=utf-8` (у PowerShell: `$env:PYTHONIOENCODING='utf-8'`) |
| `yt-dlp`: «No supported JavaScript runtime» | YouTube вимагає JS | `--js-runtimes node` (yt_fetch.py додає, якщо Node.js є в PATH) |
| `-filter_complex_script` не існує | у новій збірці ffmpeg (автор мав «ffmpeg 9») його прибрано | передавати граф аргументом або `-/filter_complex file` (vm_config.filter_script_args вибирає за версією; межа версій не перевірена) |
| Фреймворк ламається на імпорті numpy/whisper | допоміжний скрипт названий як stdlib (`inspect.py`) | не називати файли іменами модулів stdlib |
| whisper пропускає фразу / пише нісенітницю | small на російській | `medium` + `lang` + `prompt` з термінами |
| Субтитр не влазить у ширину | Arial Black 88–90 px ≈ 13 символів на 1080 | довгі пари слів ділити / зменшувати шрифт |
| `Fontconfig error: Cannot load default config file` | збірка ffmpeg без fontconfig-конфігу | ігнорувати; у drawtext задавати `fontfile=` явно (скрипти пакета беруть VM_FONT_FILE) |
| AV1-джерело декодується повільно | YouTube віддає AV1 | нормально; основи (`--stage base`) ріжуть тільки потрібні шматки |
| Комп'ютер «висне», рендер у 3 рази довший | паралельно працює whisper | спочатку транскрипт, потім рендер (на слабкому ноуті без GPU) |

Перевірка будь-якого файлу: `python scripts/verify_video.py <файл> [--fps 25] [--size 1080x1920]` (для креативів з build_creative.py: `--fps 30`) — друкує FAIL з
причиною і підказкою.
