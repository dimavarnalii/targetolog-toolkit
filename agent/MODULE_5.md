# Модуль 5: Посадкова воронка за годину

> Для ШІ-агента. Спершу прочитай `SECURITY.md` і `agent/RULES.md`.

**Результат:** Лендинг або квіз (4 теми) + сторінка подяки з подією Lead  
**Потрібно:** Python, Chrome, Google-акаунт для таблиці заявок, ID пікселя  
**Статус:** Збірку, форму, телефон, UTM і квіз перевірено автотестом у Chrome. Піксель, таблицю й хостинг на живих акаунтах не перевіряв: зробіть тестову заявку.

## GOAL
- Зібрати посадкову сторінку (landing) або квіз (quiz) для клієнта, підключити заявки й піксель, перевірити перед запуском реклами.

## READ_FIRST
- 5-landing/SKILL.md (інтерв'ю, правила текстів), 5-landing/README.md (поля brief.json), 5-landing/examples/ (5 брифів: 4 теми + квіз).

## ASK_USER (блоками)
- Бізнес і ЦА; пропозиція (що отримує людина після заявки); меседж оголошення; ДОКАЗИ (лише справжні); хто й за який час передзвонює; обмеження ніші (здоров'я, фінанси).
- Формат: лендинг (простий оффер) чи квіз (дорогий/індивідуальний продукт); тема style: fresh | dark | warm | bold; колір accent; логотип, фото; телефон, Telegram, юр. назва.

## STEPS
- 1) Створи папку клієнта з brief.json (за зразком у examples/). Фото в img/ поруч. Заголовки: акцентне слово в **...**.
- 2) python 5-landing/build_landing.py brief.json   → out/index.html, out/thanks.html. Скрипт відхилить заглушки (TODO, XXX) і довгий H1.
- 3) python 5-landing/check_page.py out/   (КРИТИЧНО / УВАГА / ОК)
- 4) python 5-landing/selftest.py brief.json   (потрібен Chrome; перевіряє форму, телефон, UTM, квіз)
- 5) Користувач: Google Таблиця, Apps Script, код з lead_endpoint.gs, Веб-застосунок (доступ: Усі); адресу /exec у tracking.endpoint; ID пікселя в tracking.pixel_id. BOT_TOKEN лише у Script Properties.
- 6) Перезбери, повтори перевірки. Публікація: папку out/ на статичний хостинг (Cloudflare Pages, Netlify, GitHub Pages) лише за згодою користувача.

## VERIFY (перед рекламою)
- Тестова заявка з телефону: рядок у таблиці з UTM, повідомлення в Telegram. Events Manager, Test Events: PageView на сторінці й Lead після заявки.
- У URL оголошення: utm_source=facebook&utm_medium=paid&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{adset.name}}&campaign_id={{campaign.id}}&adset_id={{adset.id}}&ad_id={{ad.id}}&placement={{placement}}
- Прибери демо-позначки й вигадані дані.

## NEVER
- Не вигадуй відгуків, цифр, цін, гарантій, дефіциту. Не проси BOT_TOKEN. Не публікуй без «так». Чутливі ніші: перевір правила реклами Meta.

## KNOWN_LIMITS
- Піксель, таблиця, хостинг не перевірені на живих акаунтах. Немає Conversions API (event_id для дедуплікації є), банера cookie, A/B-тесту.

