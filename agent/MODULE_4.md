# Модуль 4: Автоаудит кабінету

> Для ШІ-агента. Спершу прочитай `SECURITY.md` і `agent/RULES.md`.

**Результат:** Word-аудит на 6–8 сторінок з мітками знахідок  
**Потрібно:** Python, токен ads_read або експорти CSV з Ads Manager, адреса сайту клієнта  
**Статус:** Режим із токеном перевірено на реальному кабінеті (продажі); ліди, трафік й охоплення перевірено на перетворених реальних даних. Експорти Ads Manager і сайт-перевірку цього разу не перевіряв.

## GOAL
- Зробити Word-аудит кабінету Meta Ads: знахідки з цифрами, плейсменти, вік і стать, креативи, сайт, таблиця пріоритетів.

## READ_FIRST
- 4-audit/SKILL.md (повний процес), 4-audit/README.md (файли, правила, межі).

## ASK_USER (по одному)
- Питай по одному: режим даних (А: токен у META_TOKEN, ти його не бачиш; Б: експорти CSV з Ads Manager, які в користувача вже є), потім назва клієнта, період, адреса сайту, маржа клієнта до реклами (без маржі прибутковість не оцінюємо), чи потрібне знеособлення.
- Мета кампаній визначається автоматично (покупки, ліди, взаємодії, трафік, охоплення). Якщо цілей кілька, аналіз іде по головній за витратами, решта таблицею; змінити можна objective_focus у config.json.

## STEPS
- 0) За згодою користувача (бажано у venv): pip install -r 4-audit/requirements.txt (python-docx, matplotlib). config.json і data/ тримай поза папкою набору, скрипти викликай за повним шляхом. Windows: задай PYTHONUTF8=1. Перевірка без мережі: fetch_meta.py --config config.json --self-test.
- A) python 4-audit/fetch_meta.py --config config.json   (потрібен META_TOKEN у середовищі)
- Б) Якщо CSV вже є: поклади в data/ як campaigns, adsets, ads, placement, agegender .csv (обов'язковий лише campaigns). Інакше Ads Manager (English): Custom, MM/DD/YYYY, Update, Export as .csv. Потрібні стовпці: Amount spent (XXX), Purchases, Purchases conversion value, Impressions, Link clicks, CTR (link click-through rate), Frequency, Quality ranking, Conversion rate ranking, Landing page views, Adds to cart, Checkouts initiated, Campaign delivery, Ad delivery; для розбивок Platform, Placement, Age, Gender. Бракує: додай у колонки експорту. Валюта береться із заголовка Amount spent.
- Не читай таблицю зі сторінки (вона віртуалізована) і не експортуй зведені звіти з кількома кабінетами: туди потраплять чужі клієнти.
- Сайт: python 4-audit/site_check.py --config config.json (PSI_API_KEY теж лише змінною середовища, не в чат; без нього часто 429). Інакше заміри в браузері в data/site.json. Без цього кроку розділу про сайт у звіті не буде.
- python 4-audit/run_audit.py --config config.json --skip-fetch --skip-site   → папка work/ і Word-файл.

## VERIFY
- Відкрий work/report.json: кожна знахідка спирається на цифру. Суми витрат у кампаніях, оголошеннях і плейсментах збігаються.
- Тип аудиторії й формат визначаються за назвами: перевір шаблони в config.json. Суми по плейсментах і віку з сумою кампаній звір вручну: інструмент не попередить. Покажи користувачу три головні знахідки й що не перевірено.

## NEVER
- Не твердь прибутковість без маржі. Не публікуй документ із реальними назвами клієнта. Не змінюй кабінет. Не проси токен.

## KNOWN_LIMITS
- Результат за метою взято зі стандартних дій Meta (змінюється result_actions); звір із Ads Manager. Немає звірки з GA чи CRM. Мала вибірка (менше $50) не дає висновку.

