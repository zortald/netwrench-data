/**
 * NetWrench — приёмник отчётов «Помочь добавить роутер».
 *
 * Веб-приложение Google Apps Script, привязанное к таблице. Приложение
 * присылает POST с JSON (RouterReport, схемы 1–3), скрипт проверяет его и
 * дописывает строку на лист «reports». Схема 3 несёт улики — страницы веб-
 * интерфейса, заголовки, открытые порты, MNDP, UPnP — то, что роутер показывает
 * без входа; отчёт целиком ложится JSON-файлом в папку Диска
 * REPORTS_FOLDER, а в строку идёт сводка и ссылка на файл.
 *
 * Ключей и секретов здесь нет: адрес веб-приложения публичный, поэтому от
 * мусора защищают только проверки ниже.
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
 * Ответ всегда JSON: {"ok":true} — строка записана;
 * {"ok":false,"error":"…"} — отказ. Приложение считает отправленным только первое.
 */

const SHEET_NAME = 'reports';
const REPORTS_FOLDER = 'NetWrench router reports';
const SCHEMAS = [1, 2, 3];
/** Больше стольких отчётов в минуту со всех телефонов вместе — это не люди. */
const MAX_PER_MINUTE = 30;
/**
 * С одного устройства — не больше стольких в минуту. Повтор принимается всегда:
 * второй отчёт о том же роутере бывает богаче первого (новая версия приложения,
 * роутер поднял веб-интерфейс), и выбрасывать его как дубль — терять улики.
 * Устройство — случайный device из схемы 2+; отчёты без него считаются одним.
 */
const MAX_PER_DEVICE_PER_MINUTE = 3;
/** Отчёт с уликами — сотни килобайт: страницы целиком. Больше — уже не отчёт. */
const MAX_BODY_CHARS = 5000000;
const MAX_FIELD = 120;
const MAX_CELL = 2000;
const MAX_RADIOS = 4;
const BANDS = ['2.4', '5', '6', 'unknown'];
const CATALOG = ['none', 'partial', 'full'];
const COLUMNS = ['received', 'app', 'vendor', 'model', 'firmware', 'oui', 'detectedBy',
  'confidence', 'catalog', 'radios', 'device',
  'ports', 'servers', 'titles', 'mndp', 'upnp', 'evidence'];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function doPost(e) {
  try {
    const report = parse_(e);
    if (!report) return reply_(false, 'invalid');

    const minute = Math.floor(Date.now() / 60000);
    if (!counted_('rate:' + minute, MAX_PER_MINUTE)) return reply_(false, 'rate');
    if (!counted_('rate:' + minute + ':' + (report.device || 'nodevice'), MAX_PER_DEVICE_PER_MINUTE)) {
      return reply_(false, 'rate');
    }

    const ev = report.evidence;
    const fileUrl = ev ? saveEvidence_(report, e.postData.contents) : '';
    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      sheet_().appendRow([
        new Date(), report.app, report.vendor, report.model, report.firmware, report.oui,
        report.detectedBy, report.confidence, report.catalog,
        report.radios.map(function (r) {
          return [r.band, r.standard || '?', r.security || '?'].join(' ');
        }).join('; '),
        report.device,
        ev ? (ev.openPorts || []).join(' ') : '',
        ev ? summary_(ev.pages, function (p) { return header_(p, 'server'); }) : '',
        ev ? summary_(ev.pages, function (p) { return title_(p.body); }) : '',
        ev && ev.mndp ? JSON.stringify(ev.mndp) : '',
        ev ? (ev.upnp || []).map(function (u) { return tag_(u.description, 'modelName'); })
          .filter(String).join('; ') : '',
        fileUrl
      ].map(cell_));
    } finally {
      lock.releaseLock();
    }
    return reply_(true);
  } catch (err) {
    return reply_(false, 'error');
  }
}

/** Поля модели проверяются строго; улики — только по форме: это сырой материал, а не данные для таблицы. */
function parse_(e) {
  if (!e || !e.postData || !e.postData.contents || e.postData.contents.length > MAX_BODY_CHARS) return null;
  const r = JSON.parse(e.postData.contents);
  if (SCHEMAS.indexOf(r.schema) < 0) return null;
  const allowed = ['schema', 'app', 'vendor', 'model', 'firmware', 'oui', 'detectedBy',
    'confidence', 'radios', 'catalog', 'device', 'evidence'];
  if (Object.keys(r).some(function (k) { return allowed.indexOf(k) < 0; })) return null;
  if (!text_(r.app, true) || !text_(r.confidence, true)) return null;
  if (!text_(r.vendor) || !text_(r.model) || !text_(r.firmware) || !text_(r.detectedBy)) return null;
  if (!r.vendor && !r.model && !r.evidence) return null;
  if (r.oui != null && !/^[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}$/.test(r.oui)) return null;
  if (CATALOG.indexOf(r.catalog) < 0) return null;
  if (r.device != null && !UUID.test(r.device)) return null;
  if (!Array.isArray(r.radios) || r.radios.length > MAX_RADIOS) return null;
  if (!r.radios.every(function (x) {
    return x && BANDS.indexOf(x.band) >= 0 && text_(x.standard) && text_(x.security);
  })) return null;
  if (r.evidence != null && (typeof r.evidence !== 'object' || Array.isArray(r.evidence) ||
      !Array.isArray(r.evidence.pages) || !Array.isArray(r.evidence.openPorts))) return null;
  return {
    app: r.app, vendor: r.vendor || '', model: r.model || '', firmware: r.firmware || '',
    oui: r.oui || '', detectedBy: r.detectedBy || '', confidence: r.confidence,
    catalog: r.catalog, radios: r.radios, device: r.device || '', evidence: r.evidence || null
  };
}

/** Отчёт целиком — файлом: страницы роутера не влезают в ячейку и не должны в неё влезать. */
function saveEvidence_(report, contents) {
  const folders = DriveApp.getFoldersByName(REPORTS_FOLDER);
  const folder = folders.hasNext() ? folders.next() : DriveApp.createFolder(REPORTS_FOLDER);
  const stamp = Utilities.formatDate(new Date(), 'UTC', "yyyyMMdd'T'HHmmss'Z'");
  const name = [stamp, report.vendor || 'unknown', report.model || 'unknown',
    (report.device || 'nodevice').slice(0, 8)].join(' ').replace(/[\\/:*?"<>|]/g, '_') + '.json';
  return folder.createFile(name, contents, 'application/json').getUrl();
}

/** «порт: значение» для каждой ответившей страницы, без повторов. */
function summary_(pages, pick) {
  const seen = {};
  return (pages || []).map(function (p) {
    const v = pick(p);
    if (!v) return '';
    const line = port_(p.url) + ': ' + v;
    if (seen[line]) return '';
    seen[line] = true;
    return line;
  }).filter(String).join('; ');
}

function header_(page, name) {
  const h = page.headers || {};
  for (const k in h) if (k.toLowerCase() === name) return h[k];
  return '';
}

function title_(html) {
  const m = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html || '');
  return m ? m[1].replace(/\s+/g, ' ').trim() : '';
}

function tag_(xml, name) {
  const m = new RegExp('<' + name + '>([\\s\\S]*?)</' + name + '>', 'i').exec(xml || '');
  return m ? m[1].trim() : '';
}

function port_(url) {
  const m = /^(\w+):\/\/[^/]*?:(\d+)/.exec(url || '');
  return m ? m[1] + ':' + m[2] : url;
}

/** Строка до MAX_FIELD символов; null допустим, если не required. Формулы в таблицу не пускаем. */
function text_(v, required) {
  if (v == null) return !required;
  return typeof v === 'string' && v.length > 0 && v.length <= MAX_FIELD && !/^[=+\-@]/.test(v);
}

/** Ячейка из чужого текста: обрезана и никогда не формула. */
function cell_(v) {
  if (typeof v !== 'string') return v;
  const s = v.length > MAX_CELL ? v.slice(0, MAX_CELL) + '…' : v;
  return /^[=+\-@]/.test(s) ? "'" + s : s;
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

/** Считает обращение в счётчике [key] на эту минуту; false, если лимит уже исчерпан. */
function counted_(key, limit) {
  const cache = CacheService.getScriptCache();
  const n = Number(cache.get(key) || 0);
  if (n >= limit) return false;
  cache.put(key, String(n + 1), 120);
  return true;
}

function reply_(ok, error) {
  const body = { ok: ok };
  if (error) body.error = error;
  return ContentService.createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}
