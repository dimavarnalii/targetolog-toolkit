/**
 * Приймач заявок для landing-kit: Google Таблиця + повідомлення в Telegram.
 * Без сервера, безкоштовно.
 *
 * Налаштування (один раз):
 * 1. Створіть Google Таблицю. Розширення -> Apps Script, вставте цей код.
 * 2. Проєкт -> Налаштування -> Властивості скрипту, додайте:
 *      BOT_TOKEN  токен бота від @BotFather (необов'язково)
 *      CHAT_ID    id чату, куди слати заявки (необов'язково)
 *    Токен зберігайте ТІЛЬКИ тут, не в коді й не в чаті.
 * 3. Розгорнути -> Нове розгортання -> Веб-застосунок.
 *    Виконувати від: Мене. Доступ: Усі.
 * 4. Скопіюйте адресу розгортання (закінчується на /exec) у brief.json -> tracking.endpoint.
 * 5. Після зміни коду робіть "Нова версія" розгортання, інакше працює старий код.
 */
var SHEET = 'Заявки';
var COLS = ['ts', 'name', 'phone', 'comment', 'quiz', 'utm_source', 'utm_medium', 'utm_campaign',
            'utm_content', 'utm_term', 'ad_id', 'adset_id', 'campaign_id', 'placement', 'fbclid', 'event_id', 'page'];

function doPost(e) {
  var p = (e && e.parameter) || {};
  if (p.website) return ok_();                       // пастка для ботів
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET) || ss.insertSheet(SHEET);
  if (sh.getLastRow() === 0) sh.appendRow(COLS);
  // дубль за event_id (подвійний клік, повторне надсилання)
  var id = p.event_id;
  if (id && sh.getLastRow() > 1) {
    var col = COLS.indexOf('event_id') + 1;
    var ids = sh.getRange(2, col, sh.getLastRow() - 1, 1).getValues().join(',');
    if (ids.indexOf(id) !== -1) return ok_();
  }
  // значення з публічної форми: не дати Google Таблиці виконати їх як формулу (=, +, -, @ на початку)
  sh.appendRow(COLS.map(function (c) { var v = String(p[c] || ''); return /^[=+\-@]/.test(v) ? "'" + v : v; }));
  notify_(p);
  return ok_();
}

function notify_(p) {
  var props = PropertiesService.getScriptProperties();
  var t = props.getProperty('BOT_TOKEN'), chat = props.getProperty('CHAT_ID');
  if (!t || !chat) return;
  var txt = 'Нова заявка\n' + (p.name || '') + '\n' + (p.phone || '') +
            (p.quiz ? '\n' + p.quiz : '') + (p.comment ? '\n' + p.comment : '') +
            '\nДжерело: ' + (p.utm_source || '-') + ' / ' + (p.utm_campaign || '-');
  try {
    UrlFetchApp.fetch('https://api.telegram.org/bot' + t + '/sendMessage', {
      method: 'post', payload: { chat_id: chat, text: txt }, muteHttpExceptions: true
    });
  } catch (err) { /* заявка вже в таблиці */ }
}

function ok_() { return ContentService.createTextOutput('ok'); }
