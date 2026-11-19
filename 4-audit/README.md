# audit-kit: автоматичний аудит рекламного кабінету Meta Ads

Збирає дані кабінету, перевіряє посадкову сторінку, застосовує правила й видає оформлений Word-документ.
Кожна знахідка спирається на цифри з файлів. Висновки це гіпотези: фінальне рішення за вами.

## Що всередині

| Файл | Що робить |
|---|---|
| `fetch_meta.py` | Забирає дані з Marketing API (токен лише `ads_read`) у `data/*.csv` |
| `site_check.py` | HTML-перевірка сторінки + PageSpeed Insights → `data/site.json` |
| `analyze.py` | Правила → знахідки, таблиці, пріоритети → `work/report.json` |
| `build_docx.py` | Збирає Word з `report.json` (графіки, таблиці, мітки знахідок) |
| `run_audit.py` | Усе однією командою |
| `config.example.json` | Єдиний файл налаштувань |
| `SKILL.md` | Скіл для Claude Code: веде весь процес і вміє знімати дані через браузер |

## Підготовка (один раз)

```
pip install -r requirements.txt
```
Потрібен Python 3.10+. Інших залежностей немає.

## Два режими отримання даних

**А. З токеном (швидко).** Токен `ads_read` із модуля 1 покладіть у змінну середовища, не у файл:
Windows PowerShell: `$env:META_TOKEN = "..."`  ·  macOS/Linux: `export META_TOKEN=...`
Далі: `python run_audit.py --config config.json`

**Б. Без токена (ручний експорт з Ads Manager).** Покладіть файли в `data/` під такими іменами:

| Файл | Як отримати в Ads Manager (мова інтерфейсу: English) |
|---|---|
| `campaigns.csv` | вкладка Campaigns, потрібний період, Export → Export as .csv |
| `adsets.csv` | вкладка Ad sets, той самий період |
| `ads.csv` | вкладка Ads, той самий період |
| `placement.csv` | Campaigns + Breakdown → **Placement**, експорт |
| `agegender.csv` | Campaigns + Breakdown → **Age and gender**, експорт |
| `daily.csv` | (необов'язково) Breakdown → Time → Day, у колонках додайте Adds to cart, Checkouts initiated, Landing page views |

Обов'язковий лише `campaigns.csv`. Чим більше файлів, тим глибший аудит.
Далі: `python run_audit.py --config config.json --skip-fetch`

## Налаштування

Скопіюйте `config.example.json` у `config.json` і заповніть. Мінімум: `client_name`, `period_start`, `period_end`
(для режиму А ще `ad_account_id`). `margin_percent` (маржа клієнта до реклами) дає висновок про прибутковість.
`anonymize: true` замінює назви клієнта, кампаній і оголошень на нейтральні: для прикладів і скриншотів.

## Сайт

`python site_check.py --config config.json` потребує безкоштовного ключа PageSpeed API
(`PSI_API_KEY`; без ключа Google часто повертає помилку квоти 429). Якщо PageSpeed недоступний,
вкажіть заміри вручну у `data/site.json` (приклад у `SKILL.md`) або попросіть агента зняти їх у браузері.

## Що аудит НЕ робить

- Не знає маржі, якщо ви її не вказали, і не стверджує, що акаунт прибутковий.
- Тип аудиторії (look-alike, ретаргетинг) і формат (відео) визначає за назвами груп і оголошень. Налаштуйте шаблони в `config.json`.
- Не звіряє дані з Google Analytics чи CRM.
- Мала вибірка (менше за `min_spend_for_conclusion`) не дає висновку.
- Перевіряйте висновки перед відправкою клієнту.

## Приватність

Дані клієнтського кабінету проходять через вашу модель (Claude). Домовтеся з клієнтом. Токен лише у змінній середовища.
Для публічних прикладів завжди вмикайте `anonymize` і додатково перевіряйте текст документа очима.

## Стан перевірки

`analyze.py` і `build_docx.py` перевірено на реальних експортах Ads Manager; режим А (`fetch_meta.py`)
перевірено лише на макеті відповіді API, не на живому токені: перевірте його на своєму кабінеті.
Версію API (`api_version`) звіряйте з документацією Meta.
