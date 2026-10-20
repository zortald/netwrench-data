/**
 * NetWrench — приёмник отчётов «Сообщить о модели».
 *
 * Веб-приложение Google Apps Script, привязанное к таблице. Приложение
 * присылает POST с JSON (RouterReport, схемы 1–2), скрипт проверяет его и
 * дописывает строку на лист «reports». Ключей и секретов здесь нет: адрес
 * веб-приложения публичный, поэтому от мусора защищают только проверки ниже.
 *
 * Развёртывание:
 *   1. Создать Google Таблицу, Расширения → Apps Script, вставить этот файл.
 *   2. Развернуть → Новое развёртывание → Веб-приложение:
 *      «Выполнять от имени» — я, «У кого есть доступ» — все.
 *   3. Адрес вида https://script.google.com/macros/s/…/exec передать в
 *      приложение (gradle-свойство netwrench.routerReportUrl).
 *   4. Открыть этот адрес в браузере владельцем: пока там «Authorization
 *      needed», любой запрос получает 403. Разрешение просится заново после
 *      каждой новой версии (Управление развёртываниями → карандаш → Новая
 *      версия; адрес при этом не меняется).
 *
 * Ответ всегда JSON: {"ok":true} — строка записана (или такая уже была);
 * {"ok":false,"error":"…"} — отказ. Приложение считает отправленным только первое.
 */

const SHEET_NAME = 'reports';
const SCHEMAS = [1, 2];
/** Больше стольких отчётов в минуту со всех телефонов вместе — это не люди. */
const MAX_PER_MINUTE = 30;
/**
 * Повтор с того же устройства не пишется столько секунд. Устройство — это
 * случайный device из схемы 2 (телефон выдаёт его каждому роутеру); без него —
 * отчёт целиком. Не «производитель + модель»: у неопознанных роутеров модели
 * нет, и такой ключ склеил бы разные устройства в одно.
 */
const DUPLICATE_WINDOW_SECONDS = 6 * 60 * 60;
const MAX_FIELD = 120;
const MAX_RADIOS = 4;
const BANDS = ['2.4', '5', '6', 'unknown'];
const CATALOG = ['none', 'partial', 'full'];
const COLUMNS = ['received', 'app', 'vendor', 'model', 'firmware', 'oui', 'detectedBy',
  'confidence', 'catalog', 'radios', 'device'];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function doPost(e) {
  try {
    const report = parse_(e);
    if (!report) return reply_(false, 'invalid');

    const cache = CacheService.getScriptCache();
    const minuteKey = 'rate:' + Math.floor(Date.now() / 60000);
    const sent = Number(cache.get(minuteKey) || 0);
    if (sent >= MAX_PER_MINUTE) return reply_(false, 'rate');
    cache.put(minuteKey, String(sent + 1), 120);

    const dupKey = 'dup:' + digest_(report.device ? 'device|' + report.device : e.postData.contents);
    if (cache.get(dupKey)) return reply_(true, null, true);

    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      sheet_().appendRow([
        new Date(), report.app, report.vendor, report.model, report.firmware, report.oui,
        report.detectedBy, report.confidence, report.catalog,
        report.radios.map(function (r) {
          return [r.band, r.standard || '?', r.security || '?'].join(' ');
        }).join('; '),
        report.device
      ]);
    } finally {
      lock.releaseLock();
    }
    cache.put(dupKey, '1', DUPLICATE_WINDOW_SECONDS);
    return reply_(true);
  } catch (err) {
    return reply_(false, 'error');
  }
}

/** Только то, что описывает модель; всё остальное — отказ, а не молчаливая чистка. */
function parse_(e) {
  if (!e || !e.postData || !e.postData.contents || e.postData.contents.length > 4000) return null;
  const r = JSON.parse(e.postData.contents);
  if (SCHEMAS.indexOf(r.schema) < 0) return null;
  const allowed = ['schema', 'app', 'vendor', 'model', 'firmware', 'oui', 'detectedBy',
    'confidence', 'radios', 'catalog', 'device'];
  if (Object.keys(r).some(function (k) { return allowed.indexOf(k) < 0; })) return null;
  if (!text_(r.app, true) || !text_(r.confidence, true)) return null;
  if (!text_(r.vendor) || !text_(r.model) || !text_(r.firmware) || !text_(r.detectedBy)) return null;
  if (!r.vendor && !r.model) return null;
  if (r.oui != null && !/^[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}$/.test(r.oui)) return null;
  if (CATALOG.indexOf(r.catalog) < 0) return null;
  if (r.device != null && !UUID.test(r.device)) return null;
  if (!Array.isArray(r.radios) || r.radios.length > MAX_RADIOS) return null;
  if (!r.radios.every(function (x) {
    return x && BANDS.indexOf(x.band) >= 0 && text_(x.standard) && text_(x.security);
  })) return null;
  return {
    app: r.app, vendor: r.vendor || '', model: r.model || '', firmware: r.firmware || '',
    oui: r.oui || '', detectedBy: r.detectedBy || '', confidence: r.confidence,
    catalog: r.catalog, radios: r.radios, device: r.device || ''
  };
}

/** Строка до MAX_FIELD символов; null допустим, если не required. Формулы в таблицу не пускаем. */
function text_(v, required) {
  if (v == null) return !required;
  return typeof v === 'string' && v.length > 0 && v.length <= MAX_FIELD && !/^[=+\-@]/.test(v);
}

function sheet_() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = book.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = book.insertSheet(SHEET_NAME);
    sheet.setFrozenRows(1);
  }
  // Заголовок всегда по текущему COLUMNS: новая колонка в схеме — новая ячейка в шапке.
  sheet.getRange(1, 1, 1, COLUMNS.length).setValues([COLUMNS]);
  return sheet;
}

function digest_(s) {
  return Utilities.base64EncodeWebSafe(
    Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, s, Utilities.Charset.UTF_8));
}

function reply_(ok, error, duplicate) {
  const body = { ok: ok };
  if (error) body.error = error;
  if (duplicate) body.duplicate = true;
  return ContentService.createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}
