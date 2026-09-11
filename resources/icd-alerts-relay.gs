/**
 * ICD Alerts relay — the only thing an ICD laptop is allowed to talk to.
 *
 * PASTE THIS AS THE WHOLE FILE. Select all in Code.gs and replace. Pasting it
 * INSIDE the default `function myFunction() { }` nests doPost and doGet where
 * Apps Script cannot see them, and the deployment then answers "Script
 * function not found: doGet" -- which reads like a bad url and is not
 * (2026-09-11).
 *
 * Deploy: Deploy > New deployment > Web app, "Execute as: Me", "Who has
 * access: Anyone". The /exec url is what goes in each laptop's install.json as
 * relay_url. "Anyone" is safe here because the KEY is what authorises, not the
 * url: a caller with no valid key can do nothing at all, and every key is
 * scoped to one office.
 *
 * REDEPLOYING after an edit: Deploy > Manage deployments > pencil > Version:
 * NEW VERSION > Deploy. Leaving the version dropdown alone re-publishes the
 * old snapshot and nothing changes.
 *
 * OPENS THE WORKBOOK BY ID, so this works as a STANDALONE project and not only
 * as a container-bound one. A standalone script has no active spreadsheet, and
 * the failure that follows looks like a bad key rather than a missing
 * spreadsheet.
 *
 * THREE TABS:
 *   'Relay Keys'      Office | Key | Active | Note      <- we control this
 *   'ICD Relay'       Office | Day | Records JSON | Received At | Local Time |
 *                     Agent | Last Posted JSON | Posted At
 *   'Office Channels' Office | Owner | They Asked For | Requested At |
 *                     Channel ID | Channel Name | Approved
 *
 * THE CHANNEL IS A REQUEST, NOT A SETTING. The installer asks the owner where
 * their alerts should go and relays the answer into 'They Asked For'. Nothing
 * posts there until a human fills in Channel ID and sets Approved to TRUE.
 * A laptop can write the first four columns of its own row and NOTHING else --
 * if it could set Channel ID it could aim an office's alerts at any room in
 * the AO workspace, which is the one thing this design exists to prevent.
 *
 * ONE ROW PER OFFICE PER DAY, updated in place. Appending every sweep would be
 * ~3,000 rows a day across 52 offices and would turn the poster's read into a
 * full-sheet scan; the audit that matters (what we last posted, and when) is
 * kept on the row itself.
 *
 * A LAPTOP CAN ONLY EVER WRITE ITS OWN OFFICE'S ROW. It cannot read anything,
 * cannot see another office, and cannot touch 'Last Posted JSON' — that column
 * is ours, and it is what stops a replayed or duplicated relay from
 * re-announcing credit checks somebody already saw.
 */

// 'Lucy Access App' -- the workbook holding both tabs.
var SHEET_ID = '1_5YGHhZ0gCYVZzHl7TPnP-6_75xaI0kcjPinQdVTlKg';
var RELAY_TAB = 'ICD Relay';
var KEYS_TAB = 'Relay Keys';
var CHANNELS_TAB = 'Office Channels';

function _book() {
  return SpreadsheetApp.openById(SHEET_ID);
}

/**
 * The Day cell as 'yyyy-MM-dd', whatever Sheets decided to store.
 *
 * THIS IS THE ONE THAT BIT. Sheets silently parses '2020-01-01' into a DATE,
 * so getValues() hands back a Date object and String(it) is
 * "Wed Jan 01 2020 00:00:00 GMT-0600 (CST)" -- which never equals the
 * '2020-01-01' we are matching on. The upsert therefore never found the row
 * and appended EVERY TIME: 11 rows from 11 relays on 2026-09-11, and at 52
 * offices sweeping all day that is thousands of rows, with the poster reading
 * the stale first one. Compare on a normalised key, never on the raw cell.
 */
function _dayKey(v) {
  if (v instanceof Date) {
    return Utilities.formatDate(v, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  return String(v || '').trim();
}

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    var office = String(body.office_key || '').trim().toLowerCase();
    var key = String(body.key || '').trim();
    if (!office || !key) return _reply({ok: false, error: 'missing office or key'});
    if (!_keyIsGood(office, key)) return _reply({ok: false, error: 'not authorised'});

    var day = String(body.day || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return _reply({ok: false, error: 'bad day'});

    var records = body.records || {};
    // Store as text, sorted by the sender, so a diff of two days is readable
    // by a person looking at the sheet.
    _upsert(office, day, JSON.stringify(records),
            String(body.local_time || ''), String(body.agent || ''));

    // Optional, and sent on every sweep so a re-run of the installer can
    // change the answer. Only ever touches the columns the owner is allowed
    // to influence.
    var asked = String(body.requested_channel || '').trim();
    if (asked) _recordChannelRequest(office, String(body.owner || ''), asked);

    return _reply({ok: true, reps: Object.keys(records).length});
  } catch (err) {
    return _reply({ok: false, error: String(err)});
  }
}

function doGet() {
  // Deliberately useless. The relay is write-only for laptops.
  return _reply({ok: false, error: 'POST only'});
}

function _keyIsGood(office, key) {
  var sh = _book().getSheetByName(KEYS_TAB);
  if (!sh) return false;
  var rows = sh.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    var o = String(rows[i][0] || '').trim().toLowerCase();
    var k = String(rows[i][1] || '').trim();
    var active = String(rows[i][2] || '').trim().toUpperCase();
    if (o === office && k === key) {
      // Revoking is setting Active to anything but TRUE/YES. It takes effect
      // on the office's very next sweep, with nothing to uninstall.
      return active === 'TRUE' || active === 'YES' || active === 'Y';
    }
  }
  return false;
}

function _upsert(office, day, recordsJson, localTime, agent) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);          // two offices can relay in the same second
  try {
    var sh = _book().getSheetByName(RELAY_TAB);
    if (!sh) {
      sh = _book().insertSheet(RELAY_TAB);
      sh.appendRow(['Office', 'Day', 'Records JSON', 'Received At',
                    'Local Time', 'Agent', 'Last Posted JSON', 'Posted At']);
    }
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][0]).trim().toLowerCase() === office &&
          _dayKey(rows[i][1]) === day) {
        // Columns 3-6 only. 'Last Posted JSON' and 'Posted At' are ours.
        sh.getRange(i + 1, 3, 1, 4)
          .setValues([[recordsJson, now, localTime, agent]]);
        return;
      }
    }
    sh.appendRow([office, day, recordsJson, now, localTime, agent, '', '']);
    // Keep the day a STRING on the way in too, so the next sweep's lookup is
    // comparing like with like even if the column format is ever reset.
    sh.getRange(sh.getLastRow(), 2).setNumberFormat('@').setValue(day);
  } finally {
    lock.releaseLock();
  }
}

function _recordChannelRequest(office, owner, asked) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _book().getSheetByName(CHANNELS_TAB);
    if (!sh) return;
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][0]).trim().toLowerCase() === office) {
        // Columns 3-4 only. Channel ID, Channel Name and Approved are OURS --
        // an owner asks, a human decides.
        if (String(rows[i][2]).trim() === asked) return;   // nothing changed
        sh.getRange(i + 1, 3, 1, 2).setValues([[asked, now]]);
        // A changed request un-approves the old one: the office is asking for
        // somewhere different, and the previous approval was for a room they
        // no longer named.
        sh.getRange(i + 1, 7).setValue('');
        return;
      }
    }
    sh.appendRow([office, owner, asked, now, '', '', '']);
  } finally {
    lock.releaseLock();
  }
}

function _reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
      .setMimeType(ContentService.MimeType.JSON);
}
