# 1-dashboard: дашборд-артефакт для Claude

- `fetch_facts.py` бере з Meta Marketing API щоденні дані рівня оголошення (токен лише `ads_read`, змінна `META_TOKEN`) і пише `facts.json`, `projects.json`, `clients.json`.
- `config.example.json` приклад налаштування кабінетів.
- `page.html` сторінка дашборда для артефакта типу Dashboard (вигадані дані в шаблоні відсутні: усе читається з наборів даних).

Перевірка без мережі: `python fetch_facts.py --self-test`.
Покрокова інструкція для агента: `agent/MODULE_1.md`.
