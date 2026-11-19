# 5-landing: посадкова сторінка або квіз-воронка за одну сесію

Заповнюєте `brief.json` (або Claude заповнює його за інтерв'ю), скрипт збирає готову сторінку:
швидку, мобільну, з Meta Pixel, UTM, формою заявки і сторінкою подяки. Без бібліотек і без сервера.

## Що всередині

| Файл | Що робить |
|---|---|
| `build_landing.py` | `brief.json` → `out/index.html`, `out/thanks.html` |
| `lead_endpoint.gs` | Приймач заявок: Google Таблиця + Telegram, безкоштовно |
| `check_page.py` | Перевірка готової сторінки (критичне / увага / ок) |
| `selftest.py` | Тест форми, телефону, UTM і квізу в headless Chrome |
| `SKILL.md` | Інструкція для ШІ-агента: інтерв'ю → тексти → збірка → перевірка |
| `examples/` | П'ять прикладів брифу: лендинг у 4 темах і квіз (вигадані дані) |

Потрібно: Python 3.10+. Для `selftest.py` ще Chrome.

## Швидкий старт

```
python build_landing.py examples/landing/brief.json
python check_page.py out/
python selftest.py examples/landing/brief.json
```

## Поля brief.json

Спільні: `format` (`landing` або `quiz`), `brand`, `logo` (шлях до зображення, необов'язково),
`style` (`fresh` світла, `dark`, `warm`, `bold`), `accent` (колір кнопок, `#rrggbb`; другий відтінок `accent2` і колір тексту на кнопці рахуються самі),
`contact` (`phone`, `telegram`, `address`, `hours`), `legal` (`company`, `privacy_text`),
`form` (`title`, `subtitle`, `button`, `consent`, `fields`: `name`, `phone`, `comment`),
`tracking` (`pixel_id`, `endpoint`, `thanks_url`),
`thanks` (`title`, `text`, `next`: список кроків «що далі», `button`, `button_url`).
У заголовках `**слово**` підсвічує акцентне слово.

Лендинг:
- `hero`: `eyebrow`, `h1`, `sub`, `bullets`, `cta`, `badges` (`[{icon, t}]`), `layout` (`form` або `image`),
  `image`, `image_alt`, `floats` (плаваючі картки для `layout: image`).
- Блоки: `pains` (`title`, `sub`, `items`, `bridge`), `benefits` (`items`: `{t, d, icon}`), `steps`,
  `proof` (`numbers` для смуги цифр, `items` для відгуків), `offer`, `faq`, `final` (`title`, `text`).
- Усі блоки, крім `hero`, необов'язкові: немає в брифі, немає на сторінці.
- Іконки: `check clock shield star users bolt chat pin gift heart chart tool phone send`.

Квіз: `quiz` (`eyebrow`, `title`, `intro`, `side` (галочки ліворуч), `bonus` (`title`, `text`), `manager` (`name`, `role`, `text`),
`questions`: список `{q, options}`, `end_title`, `end_text`, `unlock`).

Фото кладіть у `img/` поруч із брифом і вказуйте шлях `img/hero.jpg`.

## Що відбувається із заявкою

1. Людина заповнює форму. Телефон приводиться до `+380XXXXXXXXX`, неправильний номер не відправляється.
2. Заявка йде на `tracking.endpoint` (Google Apps Script) разом з UTM, ID оголошення, `event_id`. Рядок у таблиці, повідомлення в Telegram.
3. Людина потрапляє на `thanks.html`, де спрацьовує подія **Lead** з тим самим `event_id` (його можна використати для дедуплікації із серверною подією).
4. Бот-пастка (приховане поле) відсікає частину спаму. Повторна відправка з тим самим `event_id` не створює дубль у таблиці.

## UTM для оголошення Meta

У полі «Параметри URL» оголошення:

```
utm_source=facebook&utm_medium=paid&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{adset.name}}&campaign_id={{campaign.id}}&adset_id={{adset.id}}&ad_id={{ad.id}}&placement={{placement}}
```

Сторінка зберігає ці параметри і додає до заявки, тож у таблиці видно, яке оголошення дало заявку.

## Налаштування заявок

Інструкція на 5 кроків у шапці `lead_endpoint.gs`. Токен Telegram-бота вводите тільки у «Властивостях скрипту»
Google, не в код, не в чат, не в бриф.

## Межі

- Піксель, приймач заявок і хостинг **не перевірені на живих акаунтах**: сторінки та їхня логіка перевірені локально (`selftest.py`),
  підключення до вашого пікселя й таблиці перевірте тестовою заявкою (Events Manager → Test Events).
- Conversions API (серверні події) не входить. `event_id` уже передається, тож дедуплікацію можна додати.
- Банера згоди на cookie немає. Для аудиторії з ЄС додайте свій CMP.
- A/B-тесту всередині немає: порівнюйте дві сторінки на двох адресах.
- Результат реклами залежить від ніші, пропозиції та бюджету. Сторінка лише прибирає технічні втрати.
- Дотримуйтесь правил реклами Meta для чутливих ніш і не вигадуйте відгуків та цифр.

## Нотатки

- **Звідки запускати.** Бриф і папка `img/` лежать у папці клієнта, поза набором. Запускайте з папки клієнта за повним шляхом до скрипта:
  `python -X utf8 <шлях_до_5-landing>/build_landing.py brief.json --out out`. `--out` рахується від поточної папки.
  Прапор `-X utf8` (або змінна `PYTHONUTF8=1`) потрібен на Windows, щоб кирилиця у виводі не псувалась. Він сумісний з `python -I`.
- **Що публікувати.** Лише папку `out/` повністю. `lead_endpoint.gs` у ній немає: його вставляють в Google Apps Script (див. шапку файлу).
- **Порожні блоки.** Будь-який блок, крім `hero`, можна не включати в бриф: його не буде на сторінці. `legal.privacy_text` теж необов'язковий.
- **Telegram.** `contact.telegram` приймає `https://t.me/name`, `t.me/name`, `@name` чи просто `name`: скрипт сам зробить повне посилання.
- **Рядок під формою.** Короткий рядок довіри під формою (наприклад, про дані) показується лише якщо ви самі вписали `form.secure`. Скрипт нічого не додає від себе.
- **Chrome для selftest.** Шукається в PATH і типових місцях; свій шлях: аргумент 2 або змінна `CHROME_PATH`. У тесті піксель вимкнено.
