# Бібліотека перебивок (B-roll) — структуру складаєте ви

У пакеті НЕМАЄ жодних відеокліпів: ліцензії на чужі кліпи не передаються. Складіть власну бібліотеку:

```
<VM_ROOT>/library/
  <категорія>/<клип>.mp4        напр. money/counting_cash.mp4, emotions/stress.mp4, phone/notification.mp4
```
Рекомендація автора: тримати кліпи 1080p+, короткі (5–15 с), без звуку або зі звуком, який ви не використовуєте.
Звідки брати: власні зйомки або сток-сервіс, чия ліцензія дозволяє комерційне використання в рекламі
(перевірте ліцензію кожного сервісу самі).

1. У `scripts/build_library_manifest.py` впишіть теги у словник `TAGS` (формат у файлі).
2. `python scripts/build_library_manifest.py` → `library/manifest.json` (id, path, category, tags, width, height, fps, duration).
   Приклад структури: `manifest.example.json`.
3. Подивитись, що є: `python ad_creatives/broll_sheet.py` (з папки проєкту) → `preview/broll_sheet.png` з підписами.
4. У `creatives.json` перебивку вказують як `"file": "lib/<категорія>/<клип без .mp4>"`.
   Автор раніше «вирівнював» fps перебивок у самому рендері (scale+fps+setsar=1), тому окремо конвертувати не треба.
