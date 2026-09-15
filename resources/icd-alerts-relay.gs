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
 * FIVE TABS:
 *   'Relay Keys'      Office | Key | Active | Note      <- we control this
 *   'ICD Relay'       Office | Day | Records JSON | Received At | Local Time |
 *                     Agent | Last Posted JSON | Posted At |
 *                     Sales JSON | Last Posted Sales JSON
 *   'ICD Knocks'      Office | Day | Rows JSON | Tracker JSON | Rep Count |
 *                     Received At | Local Time | Last Posted At
 *   'Office Channels' Office | Owner | Alerts: Wanted |
 *                     Alerts: Channels JSON | Requested At |
 *                     Alerts Approved JSON | Alerts Approved |
 *                     Knocks: Wanted | Knocks: Destinations JSON |
 *                     Knocks: Hours Note | Knocks Approved JSON |
 *                     Knocks Approved
 *
 * BOTH HALVES ARE THE SAME SHAPE: what they asked for, then what a human
 * approved. A laptop writes only the asking columns.
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
var KNOCKS_TAB = 'ICD Knocks';
var FAULTS_TAB = 'ICD Faults';
var SIGNUP_TAB = 'ICD Signup';

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

    // FAULTS ARE HANDLED BEFORE THE DAY CHECK, because they carry their own
    // day and deliberately send no top-level one -- that is what makes a
    // fault harmless to a relay running older code [[relay.report_fault]].
    if (body.fault) {
      var f = body.fault;
      var fday = String(f.day || '').trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(fday)) return _reply({ok: false, error: 'bad fault day'});
      _upsertFault(office, fday, String(f.stage || ''), String(f.summary || ''),
                   String(f.detail || ''), String(body.local_time || ''),
                   String(f.agent || ''),
                   String(f.platform || '') + ' / py' + String(f.python || ''));
      return _reply({ok: true, fault: 'recorded'});
    }

    var day = String(body.day || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return _reply({ok: false, error: 'bad day'});

    // A knocks hand-over is its own call: a laptop sends dispositions and
    // credit checks separately, because they come from different systems with
    // different outages and one must not cost the other.
    if (body.knocks_rows !== null && body.knocks_rows !== undefined) {
      _upsertKnocks(office, day, JSON.stringify(body.knocks_rows),
                    JSON.stringify(body.knocks_time_tracker || []),
                    body.knocks_rows.length, String(body.local_time || ''));
      // WHAT THEY ASKED FOR IS RECORDED HERE TOO. This used to live only in
      // the records path below, and a Box, Energy Wells or NDS office never
      // reaches it -- they have no SaraPlus, so they never post records at
      // all. Carlos relayed his board all day on 2026-09-15 and still had no
      // row on 'Office Channels', which made him impossible to approve and
      // his board impossible to post.
      _recordRequests(office, body);
      return _reply({ok: true, knock_rows: body.knocks_rows.length});
    }

    var records = body.records || {};
    // Store as text, sorted by the sender, so a diff of two days is readable
    // by a person looking at the sheet.
    _upsert(office, day, JSON.stringify(records),
            String(body.local_time || ''), String(body.agent || ''),
            JSON.stringify(body.sales || {}),
            String(body.machine || ''), String(body.machine_name || ''),
            body.desktop === true, String(body.os || ''));

    _recordRequests(office, body);

    return _reply({ok: true, reps: Object.keys(records).length});
  } catch (err) {
    return _reply({ok: false, error: String(err)});
  }
}

function doGet(e) {
  // ONE READ, AND ONLY THE PUBLIC HALF. The relay is otherwise write-only for
  // laptops. This exists because an office that signs itself up is not in
  // offices_public.json on GitHub -- that file needs a push, and the sign-up
  // form runs on Streamlit's servers where there is no repo. The installer
  // asks here instead.
  //
  // WHAT COMES BACK IS ALREADY PUBLIC: owner, label, timezone, selling hours.
  // The same facts offices_public.json publishes on GitHub for everybody.
  // NEVER the relay key -- the caller already has to hold theirs to install,
  // and handing keys out over an unauthenticated GET would undo the whole
  // point of per-office keys.
  var office = e && e.parameter ? String(e.parameter.office || '').trim().toLowerCase() : '';
  if (!office) return _reply({ok: false, error: 'POST only'});
  var sh = _book().getSheetByName(SIGNUP_TAB);
  if (!sh) return _reply({ok: false, error: 'no signups'});
  var rows = sh.getDataRange().getValues();
  var head = rows[0].map(function (h) { return String(h).trim(); });
  function col(name) { return head.indexOf(name); }
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][col('office_key')]).trim().toLowerCase() !== office) continue;
    if (String(rows[i][col('status')]).trim().toLowerCase() === 'declined') {
      return _reply({ok: false, error: 'not enrolled'});
    }
    function v(name, dflt) {
      var c = col(name);
      var out = c < 0 ? '' : String(rows[i][c]).trim();
      return out || dflt;
    }
    var owner = v('owner', '');
    // WHAT THEY ALREADY ANSWERED ON THE FORM. setup.py skips a question whose
    // answer is already in install.json, so handing these over means an office
    // that filled the form is not asked the same thing twice by the installer
    // five minutes later. They are REQUESTS either way -- a human still
    // approves where anything posts.
    function jlist(name) {
      var c = col(name);
      if (c < 0) return [];
      try {
        var parsed = JSON.parse(String(rows[i][c] || '[]'));
        return Object.prototype.toString.call(parsed) === '[object Array]' ? parsed : [];
      } catch (err) { return []; }
    }
    return _reply({ok: true, office: {
      office_key: office,
      owner: owner,
      requested_channels: jlist('alert_channels_json'),
      requested_knocks_destinations: jlist('knocks_json'),
      ov_name: v('ov_name', ''),
      // WITHOUT THIS every office installs as AT&T and a Box machine spends
      // its life trying to sign into a SaraPlus account that does not exist.
      campaign: v('campaign', 'att'),
      // THEY TYPED THESE HOURS ON THE FORM MINUTES AGO. Without this the
      // installer shows them their own answer and asks them to confirm it,
      // which is the same question twice in one sitting.
      hours_from_signup: true,
      label: v('office_label', '') || (owner.split(' ')[0] + "'s Local Office"),
      timezone: v('timezone', 'America/Chicago'),
      knocks_default_hours: {
        day_start: v('day_start', '13:30'), day_end: v('day_end', '20:30'),
        sat_start: v('sat_start', '10:45'), sat_end: v('sat_end', '17:00'),
        saturday: String(v('saturday', 'TRUE')).toUpperCase().indexOf('T') === 0,
        tz: v('timezone', 'America/Chicago')
      }
    }});
  }
  return _reply({ok: false, error: 'unknown office'});
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

function _upsert(office, day, recordsJson, localTime, agent, salesJson,
                 machine, machineName, desktop, osName) {
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
        // Sales sit in an APPENDED column (9), written separately on purpose:
        // adding them in the middle would have shifted every position this
        // function already writes, and the deployed script and the sheet
        // cannot be changed in the same instant. An older script simply never
        // writes column 9, which reads as "this office sends no sales yet"
        // rather than as corruption.
        sh.getRange(i + 1, 9).setValue(salesJson || '{}');
        _mergeMachine(sh, i + 1, machine, machineName, desktop, osName);
        return;
      }
    }
    sh.appendRow([office, day, recordsJson, now, localTime, agent, '', '',
                  salesJson || '{}', '']);
    // Keep the day a STRING on the way in too, so the next sweep's lookup is
    // comparing like with like even if the column format is ever reset.
    sh.getRange(sh.getLastRow(), 2).setNumberFormat('@').setValue(day);
    // THE FIRST RELAY OF A DAY COMES THROUGH HERE, and it was the one machine
    // that never got recorded: the row was created without it, and the next
    // machine to relay merged into an empty cell and looked like the only one.
    // Caught live 2026-09-13 -- two machines relayed and only the second
    // appeared.
    _mergeMachine(sh, sh.getLastRow(), machine, machineName, desktop, osName);
  } finally {
    lock.releaseLock();
  }
}

function _recordRequests(office, body) {
  // Optional, and sent on every sweep so a re-run of the installer can change
  // the answer. Only ever touches the columns the owner is allowed to
  // influence. Called from BOTH hand-overs: an office whose only call is the
  // knocks one still has to be able to say where its board should go.
  var chans = body.requested_channels;
  var asked = null;
  if (chans !== null && chans !== undefined) {
    asked = {
      wanted: chans.length ? chans.join(', ') : 'Not sure yet',
      json: JSON.stringify(chans)
    };
  }
  var ovName = String(body.ov_name || '').trim();
  if (ovName) {
    // Column B is the owner as WE spell them; this is how OwnerVille does.
    // Kept beside it rather than replacing it, because the two disagreeing is
    // the fact worth seeing.
    _recordOvName(office, ovName);
  }
  // A LIST. Stored as readable text for whoever reviews it AND as JSON for
  // whatever builds the schedule -- reading a schedule back out of a sentence
  // is not something anyone should have to do.
  var dests = body.requested_knocks_destinations;
  var knocks = null;
  if (dests !== null && dests !== undefined) {
    var summary = dests.length
      ? dests.map(function (d) {
          return String(d.channel || '?') + ' - ' + String(d.label || '?');
        }).join('; ')
      : 'No knocks board';
    knocks = {
      wanted: summary,
      json: JSON.stringify(dests),
      hours: String(body.requested_knocks_hours_note || '').trim()
    };
  }
  if (asked || knocks) {
    _recordChannelRequest(office, String(body.owner || ''), asked, knocks);
  }
}


function _recordOvName(office, ovName) {
  var sh = _book().getSheetByName(CHANNELS_TAB);
  if (!sh) return;
  var rows = sh.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][0]).trim().toLowerCase() === office) {
      if (String(rows[i][12] || '').trim() !== ovName) {
        sh.getRange(i + 1, 13).setValue(ovName);
      }
      return;
    }
  }
}

function _recordChannelRequest(office, owner, asked, knocks) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _book().getSheetByName(CHANNELS_TAB);
    if (!sh) return;
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][0]).trim().toLowerCase() === office) {
        var sameCh = !asked ||
                     (String(rows[i][2]).trim() === asked.wanted &&
                      String(rows[i][3] || '').trim() === asked.json);
        var sameKn = !knocks ||
                     (String(rows[i][7] || '').trim() === knocks.wanted &&
                      String(rows[i][8] || '').trim() === knocks.json &&
                      String(rows[i][9] || '').trim() === knocks.hours);
        if (sameCh && sameKn) return;              // nothing changed
        // Columns 3-4 and 8-9 only. Every *Channel ID*, *Channel Name* and
        // *Approved* column is OURS -- an owner asks, a human decides.
        if (!sameCh) {
          sh.getRange(i + 1, 3, 1, 3)
            .setValues([[asked.wanted, asked.json, now]]);
          // A changed request un-approves the old one: they are asking for
          // somewhere different, and the approval was for rooms they no
          // longer named.
          sh.getRange(i + 1, 6, 1, 2).setValues([['', '']]);
        }
        if (!sameKn) {
          sh.getRange(i + 1, 8, 1, 3)
            .setValues([[knocks.wanted, knocks.json, knocks.hours]]);
          // Both knocks approval columns are ours; clear them, because the
          // office is asking for somewhere different than was signed off.
          sh.getRange(i + 1, 11, 1, 2).setValues([['', '']]);
        }
        return;
      }
    }
    sh.appendRow([office, owner,
                  asked ? asked.wanted : '', asked ? asked.json : '', now,
                  '', '',
                  knocks ? knocks.wanted : '', knocks ? knocks.json : '',
                  knocks ? knocks.hours : '', '', '']);
  } finally {
    lock.releaseLock();
  }
}

function _upsertKnocks(office, day, rowsJson, trackerJson, count, localTime) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _book().getSheetByName(KNOCKS_TAB);
    if (!sh) {
      sh = _book().insertSheet(KNOCKS_TAB);
      sh.appendRow(['Office', 'Day', 'Rows JSON', 'Tracker JSON', 'Rep Count',
                    'Received At', 'Local Time', 'Last Posted At']);
    }
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][0]).trim().toLowerCase() === office &&
          _dayKey(rows[i][1]) === day) {
        // Columns 3-7 only. 'Last Posted At' is ours -- it is what stops the
        // same board being posted twice on one cadence tick.
        sh.getRange(i + 1, 3, 1, 5)
          .setValues([[rowsJson, trackerJson, count, now, localTime]]);
        return;
      }
    }
    sh.appendRow([office, day, rowsJson, trackerJson, count, now, localTime, '']);
    sh.getRange(sh.getLastRow(), 2).setNumberFormat('@').setValue(day);
  } finally {
    lock.releaseLock();
  }
}

function _upsertFault(office, day, stage, summary, detail, localTime,
                      agent, platform) {
  // UPSERT ON (office, day, stage, summary), NOT APPEND. A laptop whose sweep
  // is broken retries every couple of minutes, and appending would bury the
  // tab in three hundred copies of one problem -- and bury the SECOND problem
  // with it. Counting instead turns that into one row that says "47 times
  // since 09:12", which is the more useful fact anyway.
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _book().getSheetByName(FAULTS_TAB);
    if (!sh) {
      sh = _book().insertSheet(FAULTS_TAB);
      sh.appendRow(['Office', 'Day', 'Stage', 'Summary', 'Detail', 'Count',
                    'First At', 'Last At', 'Local Time', 'Agent', 'Platform',
                    'Last Posted At']);
    }
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][0]).trim().toLowerCase() === office &&
          _dayKey(rows[i][1]) === day &&
          String(rows[i][2]) === stage &&
          String(rows[i][3]) === summary) {
        var n = Number(rows[i][5] || 0) + 1;
        // Detail and Count and Last At move; First At stays. 'Last Posted At'
        // is OURS and is deliberately left alone -- except that a fault which
        // is still happening should be re-announced, and our side decides
        // that by comparing Last At against it.
        sh.getRange(i + 1, 5, 1, 1).setValue(detail);
        sh.getRange(i + 1, 6, 1, 1).setValue(n);
        sh.getRange(i + 1, 8, 1, 4).setValues([[now, localTime, agent, platform]]);
        return;
      }
    }
    sh.appendRow([office, day, stage, summary, detail, 1, now, now, localTime,
                  agent, platform, '']);
    sh.getRange(sh.getLastRow(), 2).setNumberFormat('@').setValue(day);
  } finally {
    lock.releaseLock();
  }
}

function _mergeMachine(sh, rowNum, machine, machineName, desktop, osName) {
  // MERGED, NEVER OVERWRITTEN. The whole point is to see BOTH machines: an
  // office can install on a back-office PC as a backup, and last-writer-wins
  // would hide whichever one wrote second. Column 11, appended, so nothing
  // this function already writes shifts position.
  if (!machine) return;
  var cell = sh.getRange(rowNum, 11);
  var seen = {};
  try {
    var raw = String(cell.getValue() || '{}');
    if (raw) seen = JSON.parse(raw) || {};
  } catch (err) { seen = {}; }
  seen[machine] = {name: machineName || '', last: new Date().toISOString(),
                   desktop: desktop === true, os: osName || ''};
  cell.setValue(JSON.stringify(seen));
}

function _reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
      .setMimeType(ContentService.MimeType.JSON);
}
