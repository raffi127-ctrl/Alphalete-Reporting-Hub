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
 * TABS (plus 'Headshot Jobs', 'Office Jobs' and 'Phone Lookups', documented
 * with their calls at the bottom):
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
var HEADSHOT_TAB = 'Headshot Jobs';

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

/**
 * Only the first `nCols` columns of every row -- what an upsert MATCHES on.
 *
 * THE RELAY WAS READING EVERYTHING TO FIND ONE ROW. Each upsert did
 * getDataRange().getValues() under the one script lock every office shares,
 * so every knocks hand-over read the whole of 'ICD Knocks' (13.9 MB of JSON
 * by 2026-11-18, nothing ever pruned since 9/12) and every fault read the
 * whole of 'ICD Faults' (12.4 MB of tracebacks). Calls queued behind the lock
 * past the laptop's 30-second wait: 4 relay timeouts a day in late October,
 * 931 on 2026-11-17, across 42 offices at once -- posted as "the laptop timed
 * out (slow internet)" when it was this. The office and the day are a few KB.
 */
function _keyRows(sh, nCols) {
  return sh.getRange(1, 1, Math.max(sh.getLastRow(), 1), nCols).getValues();
}

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    // LUCY'S OWN CALLS (headshots) come with the admin key, not an office
    // key, and are answered before the office check below.
    if (body.admin_key !== undefined) return _reply(_adminCall(body));
    // THE OFFICE ADMIN BROWSER EXTENSION (2026-11-04): its own sign-in, no
    // office key on the admin's computer. See OFFICE ADMINS at the bottom.
    if (body.office_admin !== undefined) return _reply(_officeAdminCall(body.office_admin));
    var office = String(body.office_key || '').trim().toLowerCase();
    var key = String(body.key || '').trim();
    if (!office || !key) return _reply({ok: false, error: 'missing office or key'});
    if (!_keyIsGood(office, key)) return _reply({ok: false, error: 'not authorised'});

    // HEADSHOTS, handed to the office's own computer to upload into its own
    // OwnerVille. Before the day check: neither call carries a day.
    if (body.headshot_jobs) return _reply(_headshotJobsFor(office));
    if (body.headshot_result) return _reply(_headshotResult(office, body.headshot_result));
    // OFFICE JOBS (office admin page -- background checks, 2026-11-02): same
    // hand-over shape as headshots, any kind. See OFFICE JOBS at the bottom.
    if (body.office_jobs) return _reply(_officeJobsFor(office));
    if (body.office_job_result) return _reply(_officeJobResult(office, body.office_job_result));
    // The office ADMIN's computer (another location) queues work for its OWN
    // office's computer and reads back how it went. Office key = own office
    // only: it can never queue or read another office's job.
    if (body.office_job_request) {
      var rq = body.office_job_request;
      // Online-presence kinds come from LUCY only (admin key): a post must
      // have passed an approver's check in Slack first.
      if (OJ_ADMIN_ONLY[String(rq.kind || '')]) return _reply({ok: false, error: 'admin only'});
      return _reply(_officeJobEnqueue({office: office, kind: rq.kind,
                                       mode: rq.mode, payload: rq.payload}));
    }
    if (body.office_job_status) return _reply(_officeJobStatus(office, String(body.office_job_status.job_id || '')));
    // THE ONBOARDING BOARD, WRITTEN BY THIS OFFICE'S OWN MACHINE (2026-11-16).
    // Before the day check, like headshots and the job queue: neither call
    // carries a day, they carry the WEEK the board is keyed on. The office key
    // has already been checked above, so a machine can only ever touch its own
    // board. See "the board, written by an office's MACHINE" at the bottom.
    if (body.board_read) return _reply(_boardWeek(office, body.board_read));
    if (body.board_seed) return _reply(_boardSeed(office, body.board_seed));
    if (body.board_tick) return _reply(_boardTick(office, body.board_tick));
    // THE SARAPLUS CODE, handed back to the Mac that asked for it
    // (icd_alerts.code_answer, 2026-10-29). Keyed like every other call, so
    // an office only ever sees an answer to its own request.
    if (body.code_poll) return _reply(_codePoll(office, String(body.code_poll.since || '')));
    // NUMBERS A PERSON LOOKED UP for the resume push (2026-11-16): the
    // office's computer asks for its own rows, marks them sent, or (the
    // admin's computer, with the office's key) adds rows for its own
    // office only. See PHONE LOOKUPS at the bottom.
    if (body.phone_lookups) return _reply(_phoneLookups(office, body.phone_lookups));

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
                    body.knocks_rows.length, String(body.local_time || ''),
                    String(body.agent || ''),
                    {id: String(body.machine || ''),
                     name: String(body.machine_name || ''),
                     desktop: body.desktop,
                     os: String(body.os || ''),
                     never_sleeps: body.never_sleeps,
                     facts: _restartFacts(body)});
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
            body.desktop === true, String(body.os || ''), _restartFacts(body));

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
      // AND THE TEXT GROUPS, for the same reason the hours are here. Aya
      // picked hers on the form on 2026-09-17 and the installer asked her
      // again minutes later, because this was the only thing the form
      // captured that never came back out. Megan: "she filled it out fully.
      // and then was asked the same questions again on the installer."
      requested_text_groups: jlist('text_groups_json'),
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
                 machine, machineName, desktop, osName, facts) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);          // two offices can relay in the same second
  try {
    var sh = _book().getSheetByName(RELAY_TAB);
    if (!sh) {
      sh = _book().insertSheet(RELAY_TAB);
      // ALL ELEVEN. This listed only the first eight, so a freshly created
      // relay tab was two columns narrower than the very next write to it.
      sh.appendRow(['Office', 'Day', 'Records JSON', 'Received At',
                    'Local Time', 'Agent', 'Last Posted JSON', 'Posted At',
                    'Sales JSON', 'Last Posted Sales JSON', 'Machines']);
    }
    var rows = _keyRows(sh, 2);    // office, day -- never the records JSON
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
        _ensureCols(sh, 11);   // column 9 below is past the created header too
        sh.getRange(i + 1, 9).setValue(salesJson || '{}');
        _mergeMachine(sh, i + 1, machine, machineName, desktop, osName, facts);
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
    _mergeMachine(sh, sh.getLastRow(), machine, machineName, desktop, osName, facts);
  } finally {
    lock.releaseLock();
  }
}

function _sameRooms(aJson, bJson) {
  // Do these two requests name the same ROOMS? Cadence, labels and whichever
  // key spelling each side happens to use are all ignored.
  //
  // WHY THIS EXISTS. The comparison above is a string match on the whole
  // request, and ANY difference cleared the approval. Two ways that bit:
  // Cyrus's cadence was changed from 15 to 30 on our side on 2026-09-15, his
  // machine put 15 back on its next sweep, and clearing the approval took his
  // board down for the rest of the day without a word. And an approval
  // written by our own tooling spells the same rooms differently from the way
  // a laptop sends them, which would have un-approved every office the moment
  // it was switched on.
  //
  // An approval is for the ROOMS a person checked. Nothing else about the
  // request is a reason to switch an office off.
  function rooms(j) {
    var out = [];
    try {
      var v = JSON.parse(j || '[]');
      if (!v || !v.length) return out;
      for (var i = 0; i < v.length; i++) {
        var d = v[i];
        var id = typeof d === 'string'
          ? d
          : String(d.channel || d.channel_id || d.channel_name || '');
        id = id.trim().toLowerCase().replace(/^#/, '');
        if (id) out.push(id);
      }
    } catch (e) {}
    return out.sort();
  }
  var a = rooms(aJson), b = rooms(bJson);
  if (a.length !== b.length) return false;
  for (var i = 0; i < a.length; i++) { if (a[i] !== b[i]) return false; }
  return true;
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
  // THE TEXTS ANSWER, which used to stop at the sign-up tab. 'Office
  // Channels' has had the four Texts columns all along and nothing ever
  // wrote them, so an office that asked to be texted looked, from the
  // approval side, like an office that had never been asked.
  var groups = body.requested_text_groups;
  var texts = null;
  if (groups !== null && groups !== undefined) {
    texts = {
      wanted: groups.length
        ? groups.map(function (t) {
            return String(t.group || '?') + ' - ' + String(t.label || '?');
          }).join('; ')
        : 'No texts',
      json: JSON.stringify(groups)
    };
  }
  if (asked || knocks || texts) {
    _recordChannelRequest(office, String(body.owner || ''), asked, knocks,
                          texts);
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

function _recordChannelRequest(office, owner, asked, knocks, texts) {
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
        // ...but only a change of ROOMS may un-approve. See _sameRooms.
        var sameRoomsKn = !knocks ||
                          _sameRooms(String(rows[i][8] || ''), knocks.json);
        var sameRoomsCh = !asked ||
                          _sameRooms(String(rows[i][3] || ''), asked.json);
        var sameTx = !texts ||
                     (String(rows[i][13] || '').trim() === texts.wanted &&
                      String(rows[i][14] || '').trim() === texts.json);
        if (sameCh && sameKn && sameTx) return;    // nothing changed
        // Columns 3-4 and 8-9 only. Every *Channel ID*, *Channel Name* and
        // *Approved* column is OURS -- an owner asks, a human decides.
        if (!sameCh) {
          sh.getRange(i + 1, 3, 1, 3)
            .setValues([[asked.wanted, asked.json, now]]);
          // ONLY A CHANGE OF ROOMS UN-APPROVES. An approval is for the rooms
          // a person checked; a different cadence, or our own wording of the
          // same rooms, is not a reason to switch an office off.
          if (!sameRoomsCh) {
            sh.getRange(i + 1, 6, 1, 2).setValues([['', '']]);
          }
        }
        if (!sameKn) {
          sh.getRange(i + 1, 8, 1, 3)
            .setValues([[knocks.wanted, knocks.json, knocks.hours]]);
          if (!sameRoomsKn) {
            sh.getRange(i + 1, 11, 1, 2).setValues([['', '']]);
          }
        }
        if (!sameTx) {
          _ensureCols(sh, 17);
          // Columns 14-15 only: 'Texts Approved JSON' and 'Texts Approved'
          // are ours, same rule as the other two -- an owner asks, a human
          // decides. And only a change of GROUPS un-approves, not a change
          // of cadence or of our own wording.
          sh.getRange(i + 1, 14, 1, 2).setValues([[texts.wanted, texts.json]]);
          if (!_sameRooms(String(rows[i][14] || ''), texts.json)) {
            sh.getRange(i + 1, 16, 1, 2).setValues([['', '']]);
          }
        }
        return;
      }
    }
    sh.appendRow([office, owner,
                  asked ? asked.wanted : '', asked ? asked.json : '', now,
                  '', '',
                  knocks ? knocks.wanted : '', knocks ? knocks.json : '',
                  knocks ? knocks.hours : '', '', '', '',
                  texts ? texts.wanted : '', texts ? texts.json : '',
                  '', '']);
  } finally {
    lock.releaseLock();
  }
}

function _ensureCols(sh, n) {
  // WIDEN BEFORE WRITING PAST THE HEADER. getRange(row, 9) does not grow a
  // sheet -- it THROWS "exceeds grid limits" -- and every such write in this
  // file sits inside doPost's try, so one narrow tab turns into "the relay
  // rejected the knocks" for every office at once.
  //
  // THIS IS NOT HYPOTHETICAL. 'ICD Knocks' was created with eight columns
  // before the machine columns existed, and the branch that writes the wider
  // header only runs when the tab is ABSENT -- so it stayed eight wide, the
  // machine merge could never have run against it, and every knocks-only
  // office (Khalil) reported no machine at all. Found 2026-09-17.
  var have = sh.getMaxColumns();
  if (have < n) { sh.insertColumnsAfter(have, n - have); }
}


function _mergeKnockMachine(sh, rowNum, agent, machine) {
  // Column 9 is the agent version, column 10 a map of machine id -> what it
  // said about itself. Merged rather than replaced, because an office may run
  // the agent on more than one computer and the quiet one is the one worth
  // seeing.
  _ensureCols(sh, 10);
  // AND BACKFILL THE HEADER. The wide header is only written when the tab is
  // created, so a tab that predates these two columns never gets their names
  // no matter how many times this is redeployed.
  if (!String(sh.getRange(1, 9).getValue() || '').trim()) {
    sh.getRange(1, 9).setValue('Agent');
    sh.getRange(1, 10).setValue('Machines');
  }
  if (agent) { sh.getRange(rowNum, 9).setValue(agent); }
  if (!machine || !machine.id) { return; }
  var cur = {};
  try { cur = JSON.parse(String(sh.getRange(rowNum, 10).getValue() || '{}')); }
  catch (e) { cur = {}; }
  cur[machine.id] = {
    name: machine.name || '',
    desktop: machine.desktop,
    os: machine.os || '',
    never_sleeps: machine.never_sleeps
  };
  var facts = machine.facts || {};
  for (var k in facts) {
    if (facts[k] !== undefined && facts[k] !== null) cur[machine.id][k] = facts[k];
  }
  sh.getRange(rowNum, 10).setValue(JSON.stringify(cur));
}


function _upsertKnocks(office, day, rowsJson, trackerJson, count, localTime,
                       agent, machine) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _book().getSheetByName(KNOCKS_TAB);
    if (!sh) {
      sh = _book().insertSheet(KNOCKS_TAB);
      sh.appendRow(['Office', 'Day', 'Rows JSON', 'Tracker JSON', 'Rep Count',
                    'Received At', 'Local Time', 'Last Posted At',
                    'Agent', 'Machines']);
    }
    var rows = _keyRows(sh, 2);    // office, day -- never the rows JSON
    var now = new Date();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][0]).trim().toLowerCase() === office &&
          _dayKey(rows[i][1]) === day) {
        // Columns 3-7 only. 'Last Posted At' is ours -- it is what stops the
        // same board being posted twice on one cadence tick.
        sh.getRange(i + 1, 3, 1, 5)
          .setValues([[rowsJson, trackerJson, count, now, localTime]]);
        // WHAT THIS MACHINE IS, on the only call these offices ever make. An
        // office with no SaraPlus never posts records, so everything we knew
        // about a computer -- its agent, whether it is a laptop, whether it
        // can sleep -- was collected on a call it never sends.
        _mergeKnockMachine(sh, i + 1, agent, machine);
        return;
      }
    }
    sh.appendRow([office, day, rowsJson, trackerJson, count, now, localTime,
                  '', '', '']);
    sh.getRange(sh.getLastRow(), 2).setNumberFormat('@').setValue(day);
    _mergeKnockMachine(sh, sh.getLastRow(), agent, machine);
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
    // office, day, stage, summary. NOT the Detail column next to them: that
    // is a full traceback per row, and it is what made this tab 12 MB.
    var rows = _keyRows(sh, 4);
    var now = new Date();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][0]).trim().toLowerCase() === office &&
          _dayKey(rows[i][1]) === day &&
          String(rows[i][2]) === stage &&
          String(rows[i][3]) === summary) {
        // The count sits past the columns read above -- one cell, this row.
        var n = Number(sh.getRange(i + 1, 6).getValue() || 0) + 1;
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

// WILL IT COME BACK AFTER A RESTART? The machine has answered this on every
// relay for weeks and nothing kept it -- so when Carlos's Mac went quiet all
// day on 2026-09-30 nobody could say whether it would have recovered on its
// own. Kept as sent: undefined (an older agent) stays absent rather than
// turning into false, because "never asked" must not read as "answered no".
function _restartFacts(body) {
  // agent_release rides in this bag ON PURPOSE: _mergeMachine merges whatever
  // keys are here into the per-machine blob in column 11, so the one fact we
  // most need -- which release this office is actually RUNNING -- is kept
  // without adding a column or redeploying the sheet's shape. An empty string
  // is kept and means "asked, has no self-update stamp yet"; a MISSING key
  // means the agent is too old to have been asked. Those read differently and
  // both are useful, so neither is turned into the other.
  return {starts_itself: body.starts_itself, sleep_off: body.sleep_off,
          powers_back_on: body.powers_back_on, auto_login: body.auto_login,
          filevault: body.filevault, agent_release: body.agent_release};
}

function _mergeMachine(sh, rowNum, machine, machineName, desktop, osName, facts) {
  // MERGED, NEVER OVERWRITTEN. The whole point is to see BOTH machines: an
  // office can install on a back-office PC as a backup, and last-writer-wins
  // would hide whichever one wrote second. Column 11, appended, so nothing
  // this function already writes shifts position.
  if (!machine) return;
  _ensureCols(sh, 11);   // never let column 11 throw and fail the whole POST
  var cell = sh.getRange(rowNum, 11);
  var seen = {};
  try {
    var raw = String(cell.getValue() || '{}');
    if (raw) seen = JSON.parse(raw) || {};
  } catch (err) { seen = {}; }
  seen[machine] = {name: machineName || '', last: new Date().toISOString(),
                   desktop: desktop === true, os: osName || ''};
  if (facts) {
    for (var k in facts) {
      if (facts[k] !== undefined && facts[k] !== null) seen[machine][k] = facts[k];
    }
  }
  cell.setValue(JSON.stringify(seen));
}

var CODES_TAB = 'Code Answers';

// 'Code Answers' is written by Lucy 1: Office | Requested At | Code |
// Written At | Taken At | Status. A code is handed out ONCE and then blanked,
// so the sheet never keeps a usable one -- they expire in minutes anyway.
function _codePoll(office, since) {
  if (!since) return {ok: false, error: 'missing since'};
  var sh = _book().getSheetByName(CODES_TAB);
  if (!sh) return {ok: true, status: 'waiting'};
  var rows = sh.getDataRange().getValues();
  for (var i = rows.length - 1; i >= 1; i--) {
    if (String(rows[i][0]).trim().toLowerCase() !== office) continue;
    if (String(rows[i][1]).trim() !== since) continue;
    var status = String(rows[i][5] || '').trim();
    if (status === 'none') return {ok: true, status: 'none'};
    var code = String(rows[i][2] || '').trim();
    if (!code || String(rows[i][4] || '').trim()) return {ok: true, status: 'taken'};
    sh.getRange(i + 1, 3).setValue('');
    sh.getRange(i + 1, 5).setValue(new Date().toISOString());
    return {ok: true, status: 'ready', code: code};
  }
  return {ok: true, status: 'waiting'};
}

function _reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
      .setMimeType(ContentService.MimeType.JSON);
}


// --- HEADSHOTS -------------------------------------------------------------
// Lucy 3 makes the white-background headshot from the office's Slack thread;
// the office's OWN computer uploads it into the office's OWN OwnerVille (an
// ICD login sees only its own reps). This tab is the hand-over between them:
//
//   'Headshot Jobs'  Job ID | Office | Name | File ID | Mode | Queued At |
//                    Status | Offered At | Result JSON | Result At |
//                    Channel | Thread TS | Posted At | Replace
//
// REPLACE = TRUE only for a redo a person asked for by name (run.py --redo):
// the one job allowed to upload over a photo already on a profile.
//
// THE PHOTO LIVES IN THIS SCRIPT'S OWN DRIVE ('Lucy Headshot Jobs' folder),
// put there by the enqueue call. So Lucy 3 needs no Drive access and nothing
// has to be shared; the file is trashed once the result has been posted.
//
// AN OFFICE ONLY EVER SEES ITS OWN JOBS. The office key already proves which
// office is asking, and both office calls filter on it: a machine cannot read
// another office's photos or answer another office's job.
//
// Lucy's calls carry the admin key, kept in Script Properties as
// LUCY_ADMIN_KEY (Project Settings > Script properties). No property set =
// every admin call is refused.
var HS = {ID: 0, OFFICE: 1, NAME: 2, FILE: 3, MODE: 4, QUEUED: 5, STATUS: 6,
          OFFERED: 7, RESULT: 8, RESULT_AT: 9, CHANNEL: 10, THREAD: 11,
          POSTED: 12, REPLACE: 13};
var HS_HEAD = ['Job ID', 'Office', 'Name', 'File ID', 'Mode', 'Queued At',
               'Status', 'Offered At', 'Result JSON', 'Result At', 'Channel',
               'Thread TS', 'Posted At', 'Replace'];
// A job handed out and never answered (laptop shut mid-upload) is offered
// again after this long. Uploading twice is safe: the uploader skips a
// profile that already has a photo.
var HS_REOFFER_MINUTES = 30;
var HS_MAX_PER_CALL = 3;

function _hsSheet() {
  var sh = _book().getSheetByName(HEADSHOT_TAB);
  if (!sh) {
    sh = _book().insertSheet(HEADSHOT_TAB);
    sh.appendRow(HS_HEAD);
  }
  return sh;
}

function _hsFolder() {
  var it = DriveApp.getFoldersByName('Lucy Headshot Jobs');
  return it.hasNext() ? it.next() : DriveApp.createFolder('Lucy Headshot Jobs');
}

function _adminCall(body) {
  var want = PropertiesService.getScriptProperties().getProperty('LUCY_ADMIN_KEY');
  if (!want || String(body.admin_key) !== want) return {ok: false, error: 'not authorised'};
  if (body.headshot_enqueue) return _headshotEnqueue(body.headshot_enqueue);
  if (body.headshot_results) return _headshotResults();
  if (body.headshot_posted) return _headshotPosted(body.headshot_posted);
  if (body.office_job_enqueue) return _officeJobEnqueue(body.office_job_enqueue);
  if (body.office_job_results) return _officeJobResults();
  if (body.office_job_collected) return _officeJobCollected(body.office_job_collected);
  if (body.office_job_log) return _officeJobLog(body.office_job_log);
  if (body.office_job_checks) return _officeJobChecks();
  if (body.office_job_checked) return _officeJobChecked(body.office_job_checked);
  if (body.phone_lookups_add) {   // a looked-up phone list for one office's push
    var pl = body.phone_lookups_add;
    return _phoneLookupsAdd(String(pl.office || '').trim().toLowerCase(), pl.rows,
                            String(pl.by || 'lucy'));
  }
  if (body.office_settings) {   // Lucy's read of what an admin set (account number, city, state)
    var st = _admSettings(String(body.office_settings.office || '').trim().toLowerCase());
    return {ok: true, appstream: st.appstream, state: st.state, city: st.city};
  }
  return {ok: false, error: 'unknown admin call'};
}

function _headshotEnqueue(j) {
  var office = String(j.office || '').trim().toLowerCase();
  var name = String(j.name || '').trim();
  var mode = String(j.mode || 'dry') === 'live' ? 'live' : 'dry';
  if (!office || !name || !j.png_b64) return {ok: false, error: 'missing office, name or photo'};
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var blob = Utilities.newBlob(Utilities.base64Decode(String(j.png_b64)),
                                 'image/png', name + ' - Headshot.png');
    var file = _hsFolder().createFile(blob);
    var id = Utilities.getUuid();
    var sh = _hsSheet();
    sh.appendRow([id, office, name, file.getId(), mode, new Date(), 'queued',
                  '', '', '', String(j.channel || ''), '', '',
                  j.replace === true ? 'TRUE' : '']);
    // Text, or Sheets turns a Slack ts like 1729951234.123456 into a number
    // and loses the digits that make it a ts.
    sh.getRange(sh.getLastRow(), HS.THREAD + 1).setNumberFormat('@')
      .setValue(String(j.thread_ts || ''));
    return {ok: true, job_id: id};
  } finally {
    lock.releaseLock();
  }
}

function _headshotJobsFor(office) {
  // NOTHING WAITING = NO LOCK. Every enrolled computer asks every 10 minutes,
  // and almost always the answer is "none" -- taking the script lock for that
  // would make every real knocks and fault write queue behind it.
  var sh0 = _book().getSheetByName(HEADSHOT_TAB);
  if (!sh0) return {ok: true, jobs: []};
  var any = sh0.getDataRange().getValues().some(function (r, i) {
    return i > 0 && String(r[HS.OFFICE]).trim().toLowerCase() === office &&
        !r[HS.RESULT_AT];
  });
  if (!any) return {ok: true, jobs: []};
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _hsSheet();
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    var out = [];
    for (var i = 1; i < rows.length && out.length < HS_MAX_PER_CALL; i++) {
      var r = rows[i];
      if (String(r[HS.OFFICE]).trim().toLowerCase() !== office) continue;
      if (r[HS.RESULT_AT]) continue;
      var st = String(r[HS.STATUS]);
      var stale = st === 'offered' && r[HS.OFFERED] instanceof Date &&
          (now - r[HS.OFFERED]) > HS_REOFFER_MINUTES * 60000;
      if (st !== 'queued' && !stale) continue;
      var b64;
      try {
        b64 = Utilities.base64Encode(DriveApp.getFileById(String(r[HS.FILE])).getBlob().getBytes());
      } catch (err) {
        sh.getRange(i + 1, HS.STATUS + 1, 1, 1).setValue('photo missing');
        sh.getRange(i + 1, HS.RESULT + 1, 1, 2).setValues([[
            JSON.stringify({status: 'error', error: 'photo file missing on our side'}), now]]);
        continue;
      }
      sh.getRange(i + 1, HS.STATUS + 1, 1, 2).setValues([['offered', now]]);
      out.push({job_id: String(r[HS.ID]), name: String(r[HS.NAME]),
                mode: String(r[HS.MODE]),
                replace: String(r[HS.REPLACE]).toUpperCase() === 'TRUE',
                png_b64: b64});
    }
    return {ok: true, jobs: out};
  } finally {
    lock.releaseLock();
  }
}

function _headshotResult(office, res) {
  var id = String(res.job_id || '');
  var status = String(res.status || '');
  if (!id || !status) return {ok: false, error: 'missing job or status'};
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _hsSheet();
    var rows = sh.getDataRange().getValues();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][HS.ID]) !== id) continue;
      // Its own office's job only -- a key for one office cannot answer for
      // another.
      if (String(rows[i][HS.OFFICE]).trim().toLowerCase() !== office) {
        return {ok: false, error: 'not your job'};
      }
      // "Try later" (OwnerVille not signed in right now) puts it back in the
      // queue instead of recording an answer.
      if (status === 'deferred') {
        sh.getRange(i + 1, HS.STATUS + 1, 1, 2).setValues([['queued', '']]);
        return {ok: true, job: 'requeued'};
      }
      sh.getRange(i + 1, HS.STATUS + 1).setValue(status);
      sh.getRange(i + 1, HS.RESULT + 1, 1, 2).setValues([[JSON.stringify(res), new Date()]]);
      return {ok: true, job: 'recorded'};
    }
    return {ok: false, error: 'no such job'};
  } finally {
    lock.releaseLock();
  }
}

function _headshotResults() {
  var rows = _hsSheet().getDataRange().getValues();
  var out = [];
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (!r[HS.RESULT_AT] || r[HS.POSTED]) continue;
    var res = {};
    try { res = JSON.parse(String(r[HS.RESULT] || '{}')); } catch (err) {}
    out.push({job_id: String(r[HS.ID]), office: String(r[HS.OFFICE]),
              name: String(r[HS.NAME]), mode: String(r[HS.MODE]),
              channel: String(r[HS.CHANNEL]), thread_ts: String(r[HS.THREAD]),
              result: res});
  }
  return {ok: true, results: out};
}

function _headshotPosted(ids) {
  var want = {};
  (ids || []).forEach(function (x) { want[String(x)] = true; });
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _hsSheet();
    var rows = sh.getDataRange().getValues();
    var n = 0;
    for (var i = 1; i < rows.length; i++) {
      if (!want[String(rows[i][HS.ID])]) continue;
      sh.getRange(i + 1, HS.POSTED + 1).setValue(new Date());
      // Done with the photo: trashed (recoverable from the bin), not deleted.
      try { DriveApp.getFileById(String(rows[i][HS.FILE])).setTrashed(true); } catch (err) {}
      n++;
    }
    return {ok: true, marked: n};
  } finally {
    lock.releaseLock();
  }
}


// --- OFFICE JOBS -----------------------------------------------------------
// Work an office ADMIN asked for on the office admin page, done on the
// office's OWN computer with the office's OWN logins (first kind:
// 'bgc_send', Sterling background-check invites). The admin's computer --
// somewhere else -- queues it with the office key (office_job_request) and
// reads it back (office_job_status); the office computer collects and
// answers with the same key. Lucy can also queue with the admin key.
//
//   'Office Jobs'  Job ID | Office | Kind | Mode | Payload JSON | Queued At |
//                  Status | Offered At | Result JSON | Result At |
//                  Collected At
//
// HANDED OUT ONCE, NEVER RE-OFFERED. Unlike a headshot, doing a job twice is
// not safe: a second run sends every applicant a second background-check
// invite. A job the computer never answers stays 'offered'; Lucy 1 reports
// it to the admin as unconfirmed ("check Sterling before pressing again").
// The computer can hand one back untouched with status 'deferred' (e.g.
// another browser had the profile) and only then is it queued again.
//
// AN OFFICE ONLY EVER SEES AND ANSWERS ITS OWN JOBS, as with headshots.
var OFFICE_JOBS_TAB = 'Office Jobs';
var OJ = {ID: 0, OFFICE: 1, KIND: 2, MODE: 3, PAYLOAD: 4, QUEUED: 5,
          STATUS: 6, OFFERED: 7, RESULT: 8, RESULT_AT: 9, COLLECTED: 10};
var OJ_HEAD = ['Job ID', 'Office', 'Kind', 'Mode', 'Payload JSON', 'Queued At',
               'Status', 'Offered At', 'Result JSON', 'Result At',
               'Collected At'];
var OJ_KINDS = {bgc_send: true, apex_week: true,
                // online presence (icd_alerts/social_post.py): the office's own Zoho
                zoho_signin: true, social_check: true, social_post: true};
var OJ_ADMIN_ONLY = {zoho_signin: true, social_check: true, social_post: true};
var OJ_MAX_PER_CALL = 2;

function _ojSheet() {
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  if (!sh) {
    sh = _book().insertSheet(OFFICE_JOBS_TAB);
    sh.appendRow(OJ_HEAD);
  }
  return sh;
}

// A social post's PHOTO is too big for a sheet cell (50k chars), so it waits
// in Drive like a headshot does; the job carries the file id and the photo is
// put back inline only when the office's computer collects the job.
function _socialFolder() {
  var it = DriveApp.getFoldersByName('Lucy Social Post Jobs');
  return it.hasNext() ? it.next() : DriveApp.createFolder('Lucy Social Post Jobs');
}
function _officeJobEnqueue(j) {
  var office = String(j.office || '').trim().toLowerCase();
  var kind = String(j.kind || '').trim();
  var mode = String(j.mode || 'dry') === 'live' ? 'live' : 'dry';
  if (!office || !OJ_KINDS[kind]) return {ok: false, error: 'missing office or unknown kind'};
  var payload = j.payload || {};
  if (payload.photo_b64) {
    var blob = Utilities.newBlob(Utilities.base64Decode(String(payload.photo_b64)),
                                 'image/jpeg', office + ' - social post.jpg');
    payload.photo_file = _socialFolder().createFile(blob).getId();
    delete payload.photo_b64;
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _ojSheet();
    // ONE SEND AT A TIME PER PERSON (Megan 2026-11-11: Raf's 16 went to
    // Sterling twice -- two sends 3 s apart, a double-click). Inside the lock,
    // so two clicks can't both get past it: if any of these emails is already
    // in a send this office hasn't finished, hand back THAT send instead of
    // queuing a second one. A finished send is the duplicate check's job.
    if (j.one_at_a_time) {
      var want = {};
      (payload.people || []).forEach(function (p) { want[String(p.email || '').toLowerCase()] = 1; });
      var rows = sh.getDataRange().getValues();
      for (var i = rows.length - 1; i >= 1; i--) {
        var r = rows[i];
        if (String(r[OJ.OFFICE]).trim().toLowerCase() !== office || String(r[OJ.KIND]) !== kind) continue;
        if (r[OJ.RESULT_AT] instanceof Date || String(r[OJ.RESULT_AT] || '')) continue;
        // a send stuck for over 30 min never blocks a real retry
        if (!(r[OJ.QUEUED] instanceof Date) || Date.now() - r[OJ.QUEUED].getTime() > 30 * 60000) continue;
        var pl = {};
        try { pl = JSON.parse(String(r[OJ.PAYLOAD] || '{}')); } catch (err) {}
        var hit = (pl.people || []).some(function (p) { return want[String(p.email || '').toLowerCase()]; });
        if (hit) return {ok: true, job_id: String(r[OJ.ID]), already_sending: true};
      }
    }
    var id = Utilities.getUuid();
    // 'checking' = held until Lucy 1 has re-read the names on ApplicantStream
    // (office_job_checked); the office's computer is only ever handed 'queued'.
    var start = String(j.status || '') === 'checking' ? 'checking' : 'queued';
    sh.appendRow([id, office, kind, mode, JSON.stringify(payload),
                  new Date(), start, '', '', '', '']);
    return {ok: true, job_id: id};
  } finally {
    lock.releaseLock();
  }
}

function _officeJobsFor(office) {
  // Nothing waiting = no lock (every enrolled computer asks often).
  var sh0 = _book().getSheetByName(OFFICE_JOBS_TAB);
  if (!sh0) return {ok: true, jobs: []};
  var any = sh0.getDataRange().getValues().some(function (r, i) {
    return i > 0 && String(r[OJ.OFFICE]).trim().toLowerCase() === office &&
        String(r[OJ.STATUS]) === 'queued';
  });
  if (!any) return {ok: true, jobs: []};
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _ojSheet();
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    var out = [];
    for (var i = 1; i < rows.length && out.length < OJ_MAX_PER_CALL; i++) {
      var r = rows[i];
      if (String(r[OJ.OFFICE]).trim().toLowerCase() !== office) continue;
      if (String(r[OJ.STATUS]) !== 'queued') continue;
      var payload = {};
      try { payload = JSON.parse(String(r[OJ.PAYLOAD] || '{}')); } catch (err) {}
      if (payload.photo_file) {
        try {
          payload.photo_b64 = Utilities.base64Encode(
              DriveApp.getFileById(String(payload.photo_file)).getBlob().getBytes());
        } catch (err) {
          sh.getRange(i + 1, OJ.STATUS + 1).setValue('error');
          sh.getRange(i + 1, OJ.RESULT + 1, 1, 2).setValues([[
              JSON.stringify({status: 'error', error: 'photo file missing on our side'}), now]]);
          continue;
        }
      }
      sh.getRange(i + 1, OJ.STATUS + 1, 1, 2).setValues([['offered', now]]);
      out.push({job_id: String(r[OJ.ID]), kind: String(r[OJ.KIND]),
                mode: String(r[OJ.MODE]), payload: payload});
    }
    return {ok: true, jobs: out};
  } finally {
    lock.releaseLock();
  }
}

function _officeJobResult(office, res) {
  var id = String(res.job_id || '');
  var status = String(res.status || '');
  if (!id || !status) return {ok: false, error: 'missing job or status'};
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _ojSheet();
    var rows = sh.getDataRange().getValues();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][OJ.ID]) !== id) continue;
      if (String(rows[i][OJ.OFFICE]).trim().toLowerCase() !== office) {
        return {ok: false, error: 'not your job'};
      }
      if (rows[i][OJ.RESULT_AT]) return {ok: true, job: 'already recorded'};
      if (status === 'deferred') {
        sh.getRange(i + 1, OJ.STATUS + 1, 1, 2).setValues([['queued', '']]);
        return {ok: true, job: 'requeued'};
      }
      sh.getRange(i + 1, OJ.STATUS + 1).setValue(status);
      sh.getRange(i + 1, OJ.RESULT + 1, 1, 2).setValues([[JSON.stringify(res), new Date()]]);
      return {ok: true, job: 'recorded'};
    }
    return {ok: false, error: 'no such job'};
  } finally {
    lock.releaseLock();
  }
}

function _officeJobResults() {
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  if (!sh) return {ok: true, results: []};
  var rows = sh.getDataRange().getValues();
  var out = [];
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (r[OJ.COLLECTED]) continue;
    var res = {};
    try { res = JSON.parse(String(r[OJ.RESULT] || '{}')); } catch (err) {}
    out.push({job_id: String(r[OJ.ID]), office: String(r[OJ.OFFICE]),
              kind: String(r[OJ.KIND]), status: String(r[OJ.STATUS]),
              offered_at: r[OJ.OFFERED] instanceof Date ? r[OJ.OFFERED].toISOString() : '',
              answered: !!r[OJ.RESULT_AT], result: res});
  }
  return {ok: true, results: out};
}

function _officeJobCollected(ids) {
  var want = {};
  (ids || []).forEach(function (x) { want[String(x)] = true; });
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _ojSheet();
    var rows = sh.getDataRange().getValues();
    var n = 0;
    for (var i = 1; i < rows.length; i++) {
      if (!want[String(rows[i][OJ.ID])]) continue;
      sh.getRange(i + 1, OJ.COLLECTED + 1).setValue(new Date());
      n++;
    }
    return {ok: true, marked: n};
  } finally {
    lock.releaseLock();
  }
}

// SECOND READER (Megan 2026-11-08): every background-check send waits here
// until Lucy 1 has re-read that ICD's OWN ApplicantStream account and found
// each person on it. Lucy 1 asks for the waiting ones, then answers with who
// it found; nobody it could not find is ever handed to the office computer.
function _officeJobChecks() {
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  if (!sh) return {ok: true, jobs: []};
  var rows = sh.getDataRange().getValues(), out = [];
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (String(r[OJ.STATUS]) !== 'checking') continue;
    var payload = {};
    try { payload = JSON.parse(String(r[OJ.PAYLOAD] || '{}')); } catch (err) {}
    out.push({job_id: String(r[OJ.ID]), office: String(r[OJ.OFFICE]).trim().toLowerCase(),
              kind: String(r[OJ.KIND]), payload: payload,
              queued_at: r[OJ.QUEUED] instanceof Date ? r[OJ.QUEUED].toISOString() : ''});
  }
  return {ok: true, jobs: out};
}

// {job_id, people: [kept], dropped: [{name, email, why}], error}
// people left -> 'queued' for the office computer, with ONLY those people.
// none left, or Lucy couldn't check -> answered as an error; nothing is sent.
function _officeJobChecked(c) {
  var id = String(c.job_id || '');
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _ojSheet();
    var rows = sh.getDataRange().getValues();
    for (var i = 1; i < rows.length; i++) {
      if (String(rows[i][OJ.ID]) !== id) continue;
      if (String(rows[i][OJ.STATUS]) !== 'checking') return {ok: true, job: 'not waiting'};
      var payload = {};
      try { payload = JSON.parse(String(rows[i][OJ.PAYLOAD] || '{}')); } catch (err) {}
      var kept = (c.people || []), dropped = (c.dropped || []);
      payload.dropped = dropped;
      if (c.error || !kept.length) {
        var why = c.error ? String(c.error)
            : "None of them were found on this office's ApplicantStream list, so nothing was sent.";
        sh.getRange(i + 1, OJ.PAYLOAD + 1).setValue(JSON.stringify(payload));
        sh.getRange(i + 1, OJ.STATUS + 1).setValue('error');
        sh.getRange(i + 1, OJ.RESULT + 1, 1, 2).setValues([[
            JSON.stringify({status: 'error', error: why, dropped: dropped}), new Date()]]);
        return {ok: true, job: 'stopped'};
      }
      payload.people = kept;
      sh.getRange(i + 1, OJ.PAYLOAD + 1).setValue(JSON.stringify(payload));
      sh.getRange(i + 1, OJ.STATUS + 1).setValue('queued');
      return {ok: true, job: 'cleared'};
    }
    return {ok: false, error: 'no such job'};
  } finally {
    lock.releaseLock();
  }
}

function _officeJobStatus(office, id) {
  if (!id) return {ok: false, error: 'missing job'};
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  if (!sh) return {ok: false, error: 'no such job'};
  var rows = sh.getDataRange().getValues();
  for (var i = rows.length - 1; i >= 1; i--) {
    var r = rows[i];
    if (String(r[OJ.ID]) !== id) continue;
    if (String(r[OJ.OFFICE]).trim().toLowerCase() !== office) return {ok: false, error: 'not your job'};
    var res = {};
    try { res = JSON.parse(String(r[OJ.RESULT] || '{}')); } catch (err) {}
    var pl = {};
    try { pl = JSON.parse(String(r[OJ.PAYLOAD] || '{}')); } catch (err) {}
    return {ok: true, job_id: id, status: String(r[OJ.STATUS]), dropped: pl.dropped || [],
            offered_at: r[OJ.OFFERED] instanceof Date ? r[OJ.OFFERED].toISOString() : '',
            answered: !!r[OJ.RESULT_AT], result: res};
  }
  return {ok: false, error: 'no such job'};
}


// --- PHONE LOOKUPS (numbers a person found for the resume push) ------------
// The One App at a time walk flags an applicant whose record and resume both
// carry no number, and a person then finds it (Indeed's Call pop-up). The
// office's computer, which does the pushing, holds no Google access -- so the
// number comes back to it through here (Carlos 2026-11-16, thirty of his).
//
//   'Phone Lookups'  Office | Office ID | Name | Account | Phone | Added At |
//                    Added By | Note | Fetched At | Sent At | Status
//
// WHO WRITES ROWS: our side (the admin key, or a person typing into the tab),
// or the office's OWN key for its own office only -- the same rule as
// office_job_request. An office reads and marks only its own rows; it can
// never see another office's. Office ID narrows a key that pushes several
// offices (Raf's three); a blank Office ID is for all of them.
//
// A ROW IS DONE when Sent At is set (the office typed the number in and the
// send landed). Any other status -- a refused send, a number that is not ten
// digits -- leaves Sent At blank and the status on the row, for a person.
// NOTHING HERE EVER REMOVES A ROW OR AN APPLICANT.
var PHONE_LOOKUPS_TAB = 'Phone Lookups';
var PL = {OFFICE: 0, OFFICE_ID: 1, NAME: 2, ACCOUNT: 3, PHONE: 4, ADDED: 5,
          BY: 6, NOTE: 7, FETCHED: 8, SENT: 9, STATUS: 10};
var PL_HEAD = ['Office', 'Office ID', 'Name', 'Account', 'Phone', 'Added At',
               'Added By', 'Note', 'Fetched At', 'Sent At', 'Status'];
var PL_MAX_PER_CALL = 200;

function _plSheet() {
  var sh = _book().getSheetByName(PHONE_LOOKUPS_TAB);
  if (!sh) {
    sh = _book().insertSheet(PHONE_LOOKUPS_TAB);
    sh.appendRow(PL_HEAD);
  }
  _ensureCols(sh, PL_HEAD.length);
  return sh;
}

function _plKey(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

function _phoneLookups(office, a) {
  a = a || {};
  if (a.add) return _phoneLookupsAdd(office, a.add, 'office:' + office);
  if (a.sent) return _phoneLookupsSent(office, a.sent);
  return _phoneLookupsFor(office, String(a.office_id || '').trim());
}

function _phoneLookupsAdd(office, rows, by) {
  if (!office || Object.prototype.toString.call(rows) !== '[object Array]') {
    return {ok: false, error: 'missing office or rows'};
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _plSheet();
    var have = sh.getDataRange().getValues();
    // A NAME ALREADY WAITING (unsent) FOR THIS OFFICE IS NOT ADDED TWICE, so a
    // list dropped twice doubles nobody. A finished row may repeat: the same
    // person can apply again next month with the same number.
    var waiting = {};
    for (var i = 1; i < have.length; i++) {
      if (String(have[i][PL.OFFICE]).trim().toLowerCase() !== office) continue;
      if (String(have[i][PL.SENT] || '').trim()) continue;
      waiting[_plKey(have[i][PL.OFFICE_ID]) + '|' + _plKey(have[i][PL.NAME])] = true;
    }
    var now = new Date();
    var out = [];
    var skipped = 0;
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j] || {};
      var name = String(r.name || '').trim();
      var phone = String(r.phone || '').trim();
      if (!name || !phone) { skipped++; continue; }
      var k = _plKey(r.office_id) + '|' + _plKey(name);
      if (waiting[k]) { skipped++; continue; }
      waiting[k] = true;
      out.push([office, String(r.office_id || '').trim(), name,
                String(r.account || '').trim(), phone, now, String(by || ''),
                String(r.note || '').slice(0, 200), '', '', '']);
    }
    if (out.length) {
      sh.getRange(sh.getLastRow() + 1, 1, out.length, PL_HEAD.length).setValues(out);
    }
    return {ok: true, added: out.length, skipped: skipped};
  } finally {
    lock.releaseLock();
  }
}

function _phoneLookupsFor(office, officeId) {
  // Nothing waiting = no lock, no write: every pushing office asks on every
  // walk that meets an applicant with no number.
  var sh = _book().getSheetByName(PHONE_LOOKUPS_TAB);
  if (!sh) return {ok: true, lookups: []};
  var rows = sh.getDataRange().getValues();
  var out = [];
  var hit = [];
  for (var i = 1; i < rows.length && out.length < PL_MAX_PER_CALL; i++) {
    var r = rows[i];
    if (String(r[PL.OFFICE]).trim().toLowerCase() !== office) continue;
    var rid = String(r[PL.OFFICE_ID] || '').trim();
    if (officeId && rid && rid !== officeId) continue;
    if (String(r[PL.SENT] || '').trim()) continue;
    if (!String(r[PL.NAME] || '').trim() || !String(r[PL.PHONE] || '').trim()) continue;
    out.push({row: i + 1, office_id: rid, name: String(r[PL.NAME]).trim(),
              account: String(r[PL.ACCOUNT] || '').trim(),
              phone: String(r[PL.PHONE]).trim()});
    hit.push(i + 1);
  }
  if (hit.length) {
    // Fetched At, written as one column so a 200-row list is one write.
    _ensureCols(sh, PL_HEAD.length);
    var n = rows.length - 1;
    var col = sh.getRange(2, PL.FETCHED + 1, n, 1).getValues();
    var now = new Date();
    for (var h = 0; h < hit.length; h++) col[hit[h] - 2][0] = now;
    sh.getRange(2, PL.FETCHED + 1, n, 1).setValues(col);
  }
  return {ok: true, lookups: out};
}

function _phoneLookupsSent(office, items) {
  if (Object.prototype.toString.call(items) !== '[object Array]') {
    return {ok: false, error: 'missing items'};
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _plSheet();
    var rows = sh.getDataRange().getValues();
    var now = new Date();
    var marked = 0;
    for (var j = 0; j < items.length; j++) {
      var it = items[j] || {};
      var st = String(it.status || '').trim().slice(0, 60);
      if (!st) continue;
      // The row the office was handed, if it still is that person; else the
      // office's first unsent row of that name (rows moved under it).
      var want = _plKey(it.name);
      var i = parseInt(it.row, 10) - 1;
      var found = -1;
      if (i >= 1 && i < rows.length && _plKey(rows[i][PL.NAME]) === want &&
          String(rows[i][PL.OFFICE]).trim().toLowerCase() === office) {
        found = i;
      } else {
        for (var k = 1; k < rows.length; k++) {
          if (String(rows[k][PL.OFFICE]).trim().toLowerCase() !== office) continue;
          if (String(rows[k][PL.SENT] || '').trim()) continue;
          if (_plKey(rows[k][PL.NAME]) !== want) continue;
          found = k;
          break;
        }
      }
      if (found < 0) continue;
      if (String(rows[found][PL.SENT] || '').trim()) continue;   // already done
      sh.getRange(found + 1, PL.STATUS + 1).setValue(st);
      if (st.indexOf('sent') === 0) {
        sh.getRange(found + 1, PL.SENT + 1).setValue(now);
        rows[found][PL.SENT] = now;
      }
      marked++;
    }
    return {ok: true, marked: marked};
  } finally {
    lock.releaseLock();
  }
}


// --- OFFICE ADMINS (the browser extension) ----------------------------------
// One login per office admin (Raf 2026-11-01), used by the Lucy Office Admin
// Chrome extension on the admin's computer -- which holds NO office key and
// no Google login, only a sign-in that lasts the working day.
//
// ONE ADMIN, SEVERAL OFFICES (Megan 2026-11-04): one row per (admin, office);
// the same username on several rows = an admin who runs several offices.
// Password = the row with a hash (relay_admins keeps them the same).
//
//   'Office Admins'   Username | Office | Salt | Hash | Active | Mode | Name |
//                     Last Login | AppStream   <- we fill it (office_admin.relay_admins)
//   'Office Settings' Office | State | City | Updated By | Updated At | AppStream
//
// APPSTREAM = the office's ApplicantStream account number. The admin can
// enter / change it (and city + state) per office in the extension; it is
// how the calendar on screen is matched to one of their offices -- no match,
// nothing is sent. 'Office Settings' wins over the admin row's starting value.
//
// Hash = SHA-256 hex of (salt + password); passwords are long, generated ones,
// and sign-in is rate-limited, so a single round is enough here.
// MODE (dry | live) is ours, per admin-office row: the extension never says.
// SIGN IN ONCE PER COMPUTER (Megan 2026-11-04: "the admin won't have to
// login though?"): a session is a random token kept 90 days in Script
// Properties (the cache tops out at 6 h). Every call re-checks the admin's
// rows, so turning a login off (relay_admins --disable) ends it at once.
var ADMINS_TAB = 'Office Admins';
var ADM = {USER: 0, OFFICE: 1, SALT: 2, HASH: 3, ACTIVE: 4, MODE: 5, NAME: 6, LAST: 7, APPSTREAM: 8};
var ADM_HEAD = ['Username', 'Office', 'Salt', 'Hash', 'Active', 'Mode', 'Name', 'Last Login', 'AppStream'];
var SETTINGS_TAB = 'Office Settings';
// 'Approved Accounts' is the GUARD (Megan 2026-11-06): only Megan sets it
// (relay_admins --accounts). Admins can use these accounts and no others, so a
// calendar from someone else's office can never send through this Sterling.
// 'Onboarding Sheet' is the office's OWN metrics workbook id -- the board
// lives on an 'Onboarding' tab in it, so each office sees its own people and
// nobody else's (Megan 2026-11-08: "add a tab to their metrics sheet?").
var SET_HEAD = ['Office', 'State', 'City', 'Updated By', 'Updated At', 'AppStream', 'Approved Accounts', 'Onboarding Sheet', 'Owner'];
var BOARD_TAB = 'Onboarding';
var BOARD_HEADER_ROW = 1;
var BOARD_FIRST_ROW = 2;
var SESSION_DAYS = 90;
var MAX_TRIES = 5;

function _admSheet(name, head) {
  var sh = _book().getSheetByName(name);
  if (!sh) { sh = _book().insertSheet(name); sh.appendRow(head); }
  return sh;
}

function _sha256Hex(text) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text,
                                      Utilities.Charset.UTF_8);
  return bytes.map(function (b) { var h = (b & 0xff).toString(16); return h.length < 2 ? '0' + h : h; }).join('');
}

function _digits(v) { return String(v || '').replace(/\D/g, ''); }
// One office can use several ApplicantStream accounts that all go to the same
// Sterling (Megan 2026-11-06: every one of Raf's accounts). Stored "11280, 24153".
function _accounts(v) {
  var seen = {}, out = [];
  (String(v || '').match(/\d+/g) || []).forEach(function (n) { if (!seen[n]) { seen[n] = 1; out.push(n); } });
  return out.join(', ');
}

// SIGN IN = FIRST + LAST NAME (Megan 2026-11-10: "sign in should always be the
// users first and last name - that's an easy thing to remember"). Spaces,
// capitals and punctuation never matter: "Cody Cannon", "cody  cannon" and
// "CodyCannon" are one admin. Older logins made from a first name ("cody")
// still work, and so does their full name off the Name column.
function _admKey(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

// Every row for this admin: [{i, r}]. Username first; else the Name column --
// but only when that name is ONE admin's (two people with one name = no match).
function _admRows(username) {
  var rows = _admSheet(ADMINS_TAB, ADM_HEAD).getDataRange().getValues();
  var u = _admKey(username);
  if (!u) return [];
  var pick = function (want) {
    var out = [];
    for (var i = 1; i < rows.length; i++) {
      if (_admKey(rows[i][ADM.USER]) === want) out.push({i: i, r: rows[i]});
    }
    return out;
  };
  var out = pick(u);
  if (out.length) return out;
  var users = {};
  for (var i = 1; i < rows.length; i++) {
    if (_admKey(rows[i][ADM.NAME]) === u) users[_admKey(rows[i][ADM.USER])] = 1;
  }
  var names = Object.keys(users);
  return names.length === 1 ? pick(names[0]) : [];
}

function _session(token) {
  if (!token) return null;
  var props = PropertiesService.getScriptProperties();
  var raw = props.getProperty('adm:' + token);
  if (!raw) return null;
  var sess = JSON.parse(raw);
  if (Date.now() > sess.exp) { props.deleteProperty('adm:' + token); return null; }
  // Still an admin? Offices re-read, so a login turned off ends right away
  // and an office added/removed shows up without signing in again.
  var rows = _admRows(sess.username).filter(function (h) { return String(h.r[ADM.ACTIVE]).toUpperCase() === 'TRUE'; });
  if (!rows.length) { props.deleteProperty('adm:' + token); return null; }
  sess.offices = rows.map(function (h) { return String(h.r[ADM.OFFICE]).trim().toLowerCase(); });
  return sess;
}

function _officeAdminCall(a) {
  var what = String(a.call || '');
  if (what === 'login') return _admLogin(a);
  var sess = _session(String(a.token || ''));
  if (!sess) return {ok: false, error: 'signed out', signed_out: true};
  if (what === 'whoami') return _admWhoami(sess);
  // Everything else is for ONE of this admin's offices.
  var office = String(a.office || '').trim().toLowerCase();
  if (sess.offices.indexOf(office) < 0) return {ok: false, error: "That isn't one of your offices."};
  if (what === 'set_office') return _admSetOffice(sess, office, a);
  if (what === 'send') return _admSend(sess, office, a);
  if (what === 'apex_week') return _admApexWeek(sess, office, a);
  if (what === 'board_week') return _boardWeek(office, a);
  if (what === 'board_mark') return _boardMark(office, a);
  if (what === 'board_classroom') return _boardClassroom(office, a);
  if (what === 'board_gender') return _boardGender(office, a);
  if (what === 'board_location') return _boardLocation(office, a);
  if (what === 'status') return _officeJobStatus(office, String(a.job_id || ''));
  if (what === 'already') return _admAlready(office);
  if (what === 'bg_status') return _admBgStatus(office);
  return {ok: false, error: 'unknown call'};
}

function _admLogin(a) {
  var cache = CacheService.getScriptCache();
  var user = _admKey(a.username);
  var triesKey = 'admtries:' + user;
  var tries = Number(cache.get(triesKey) || 0);
  if (tries >= MAX_TRIES) return {ok: false, error: 'Too many tries. Wait 15 minutes.'};
  var rows = _admRows(user).filter(function (h) { return String(h.r[ADM.ACTIVE]).toUpperCase() === 'TRUE'; });
  var keyRow = rows.filter(function (h) { return String(h.r[ADM.HASH]); })[0];
  var good = keyRow &&
      _sha256Hex(String(keyRow.r[ADM.SALT]) + String(a.password || '')) === String(keyRow.r[ADM.HASH]);
  if (!good) {
    cache.put(triesKey, String(tries + 1), 900);
    return {ok: false, error: "That name and password don't match."};
  }
  cache.remove(triesKey);
  var token = Utilities.getUuid();
  // The session holds the sheet's own username, whatever was typed.
  var sess = {username: String(keyRow.r[ADM.USER]).trim().toLowerCase(),
              name: String(keyRow.r[ADM.NAME] || user),
              offices: rows.map(function (h) { return String(h.r[ADM.OFFICE]).trim().toLowerCase(); })};
  sess.exp = Date.now() + SESSION_DAYS * 86400000;
  PropertiesService.getScriptProperties().setProperty('adm:' + token, JSON.stringify(sess));
  var sh = _admSheet(ADMINS_TAB, ADM_HEAD), now = new Date();
  rows.forEach(function (h) { sh.getRange(h.i + 1, ADM.LAST + 1).setValue(now); });
  var who = _admWhoami(sess);
  who.token = token;
  return who;
}

// BY HEADER NAME, never by position. Two people added a column to this tab on
// the same day -- 'Onboarding Sheet' and 'Owner' -- and whichever landed second
// shifted the other's index, so a read by number returned the wrong cell
// silently. The header is the only thing that survives a new column.
function _setCols(sh) {
  var head = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), SET_HEAD.length))
               .getValues()[0];
  var at = {}, i;
  for (i = 0; i < head.length; i++) {
    var name = String(head[i] || '').trim();
    if (name) at[name] = i;
  }
  // Any column SET_HEAD knows about and the tab does not gets appended, rather
  // than the whole header being rewritten over somebody else's work.
  var next = head.length;
  for (i = 0; i < SET_HEAD.length; i++) {
    if (!(SET_HEAD[i] in at)) {
      sh.getRange(1, next + 1).setValue(SET_HEAD[i]);
      at[SET_HEAD[i]] = next;
      next++;
    }
  }
  return at;
}

function _admSettings(office) {
  var sh = _admSheet(SETTINGS_TAB, SET_HEAD);
  var at = _setCols(sh);
  var cell = function (r, name) {
    return (name in at && at[name] < r.length) ? String(r[at[name]] || '').trim() : '';
  };
  var rows = sh.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][0]).trim().toLowerCase() === office) {
      return {row: i, cols: at,
              state: cell(rows[i], 'State'), city: cell(rows[i], 'City'),
              appstream: _accounts(cell(rows[i], 'AppStream')),
              approved: _accounts(cell(rows[i], 'Approved Accounts')),
              sheet: cell(rows[i], 'Onboarding Sheet'),
              owner: cell(rows[i], 'Owner')};
    }
  }
  return {row: -1, cols: at, state: '', city: '', appstream: '', approved: '',
          sheet: '', owner: ''};
}

// Every OTHER office that has this ApplicantStream account approved. One
// account = one office, always (Megan 2026-11-08: an admin for 2 ICDs must
// have NO way to send one ICD's applicants through the other's Sterling).
function _admOtherOwnersOf(acct, office) {
  var sh = _admSheet(SETTINGS_TAB, SET_HEAD);
  var at = _setCols(sh);
  var cell = function (r, name) {
    return (name in at && at[name] < r.length) ? String(r[at[name]] || '').trim() : '';
  };
  var rows = sh.getDataRange().getValues(), out = [];
  for (var i = 1; i < rows.length; i++) {
    var o = String(rows[i][0]).trim().toLowerCase();
    if (!o || o === office) continue;
    if (_accounts(cell(rows[i], 'Approved Accounts')).split(', ').indexOf(acct) >= 0) out.push(o);
  }
  return out;
}

// One office as the extension sees it.
function _admOffice(sess, office) {
  var row = _admRows(sess.username).filter(function (h) {
    return String(h.r[ADM.OFFICE]).trim().toLowerCase() === office;
  })[0];
  var set = _admSettings(office);
  return {office: office,
          appstream: set.appstream || (row ? _accounts(row.r[ADM.APPSTREAM]) : ''),
          approved: set.approved, owner: set.owner,
          state: set.state, city: set.city,
          mode: row && String(row.r[ADM.MODE]).trim().toLowerCase() === 'live' ? 'live' : 'dry'};
}

function _admWhoami(sess) {
  return {ok: true, name: sess.name, username: sess.username,
          offices: sess.offices.map(function (o) { return _admOffice(sess, o); })};
}

function _admSetOffice(sess, office, a) {
  var state = String(a.state || '').trim(), city = String(a.city || '').trim().replace(/\s+/g, ' ');
  var appstream = _accounts(a.appstream);
  if (!state || !city) return {ok: false, error: 'Pick the state and type the city.'};
  if (!appstream) return {ok: false, error: 'Type the ApplicantStream account number(s).'};
  var ok = _accounts(_admSettings(office).approved).split(', ').filter(String);
  var bad = appstream.split(', ').filter(function (n) { return ok.indexOf(n) < 0; });
  if (bad.length) {
    return {ok: false, error: 'Account ' + bad.join(', ') + (bad.length > 1 ? " aren't" : " isn't") +
        " approved for this office" + (ok.length ? ' (approved: ' + ok.join(', ') + ')' : '') +
        '. Ask Megan to add it.'};
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = _admSheet(SETTINGS_TAB, SET_HEAD);
    var cur = _admSettings(office);
    // Each value under its OWN header, one cell at a time. Writing a fixed
    // span of columns was safe only while nobody added one in the middle, and
    // two columns arrived on the same day. Approved Accounts, Onboarding Sheet
    // and Owner are never touched here.
    var put = {Office: office, State: state, City: city,
               'Updated By': sess.username, 'Updated At': new Date(),
               AppStream: appstream};
    if (cur.row > 0) {
      Object.keys(put).forEach(function (name) {
        if (name in cur.cols) sh.getRange(cur.row + 1, cur.cols[name] + 1).setValue(put[name]);
      });
    } else {
      var line = [];
      Object.keys(put).forEach(function (name) {
        if (name in cur.cols) line[cur.cols[name]] = put[name];
      });
      for (var c = 0; c < line.length; c++) if (line[c] === undefined) line[c] = '';
      sh.appendRow(line);
    }
    return {ok: true, office: _admOffice(sess, office)};
  } finally {
    lock.releaseLock();
  }
}

function _admSend(sess, office, a) {
  var o = _admOffice(sess, office);
  if (!o.state || !o.city) return {ok: false, error: "Set this office's city and state first."};
  // THE GUARD: the calendar's own account number must be approved for this
  // office (and switched on by its admin). Anything else sends nothing.
  // Several accounts can go in one send ("11280, 11901"): EVERY one must pass.
  var acct = _accounts(a.appstream);
  var approved = String(o.approved || '').split(', ').filter(String);
  var chosen = String(o.appstream || '').split(', ').filter(String);
  if (!acct) return {ok: false, error: "Couldn't tell which ApplicantStream account this calendar is. Reload the calendar and try again."};
  var off = acct.split(', ').filter(function (n) { return approved.indexOf(n) < 0 || chosen.indexOf(n) < 0; });
  if (off.length) {
    return {ok: false, error: 'ApplicantStream account ' + off.join(', ') + " isn't approved for this office, so nothing was sent. Ask Megan to add it."};
  }
  var shared = acct.split(', ').filter(function (n) { return _admOtherOwnersOf(n, office).length; });
  if (shared.length) {
    return {ok: false, error: 'ApplicantStream account ' + shared.join(', ') +
        ' is approved for more than one office, so nothing was sent. Ask Megan to fix it.'};
  }
  var people = (a.people || []).filter(function (p) {
    return p && String(p.first_name || '').trim() && String(p.last_name || '').trim() &&
        String(p.email || '').indexOf('@') > 0;
  }).map(function (p) {
    return {first_name: String(p.first_name).trim(), last_name: String(p.last_name).trim(),
            email: String(p.email).trim()};
  });
  if (!people.length) return {ok: false, error: 'Nobody with a name and email was picked.'};
  // Before the duplicate check: the admin answers 'is this many right?' first.
  var usual = _admUsualPerDay(office);
  if (!a.big_ok && people.length > BIG_FLOOR && (usual === 0 || people.length > BIG_TIMES * usual)) {
    return {ok: false, needs_big_confirm: true, count: people.length, usual: Math.round(usual),
            error: 'This is a much bigger send than usual.'};
  }
  // ALREADY SENT = ASK, NEVER A SILENT SECOND INVITE (Megan 2026-11-06). A bulk
  // upload re-invited an email Sterling had invited two days before, so the
  // admin is shown who was already sent and decides: resend 'all' sends them
  // again too, 'skip' drops them and sends the rest. No answer = nothing sent.
  var sent = _admAlready(office).sent;
  var dups = people.filter(function (p) { return sent[p.email.toLowerCase()]; })
      .map(function (p) {
        return {name: p.first_name + ' ' + p.last_name, email: p.email, sent_on: sent[p.email.toLowerCase()]};
      });
  var resend = String(a.resend || '');
  if (dups.length && resend !== 'all' && resend !== 'skip') {
    return {ok: false, needs_confirm: true, duplicates: dups,
            error: 'Some of these were already sent a background check.'};
  }
  if (dups.length && resend === 'skip') {
    people = people.filter(function (p) { return !sent[p.email.toLowerCase()]; });
    if (!people.length) return {ok: true, skipped_all: true, job_id: ''};
  }
  var source = String(a.source || '') === 'next_week' ? 'next_week' : 'today';
  return _officeJobEnqueue({office: office, kind: 'bgc_send', mode: o.mode, status: 'checking',
                            one_at_a_time: true,
                            payload: {people: people, by: sess.username, appstream: acct,
                                      source: source, week_monday: String(a.week_monday || ''),
                                      location: {country: 'United States', state: o.state, city: o.city}}});
}

// NEXT WEEK'S STARTS (Megan 2026-11-06): the extension reads who starts next
// week off the office's own ApplicantStream calendars; this hands it each
// person's background-check status from the Sterling result EMAILS (Lucy 1
// copies them to the 'BG Status' tab -- office_admin/roster_publish.py).
var BG_TAB = 'BG Status';
function _admBgStatus(office) {
  var sh = _book().getSheetByName(BG_TAB);
  if (!sh) return {ok: true, updated: '', people: []};
  var rows = sh.getDataRange().getValues(), out = [], updated = '';
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (String(r[0]).trim().toLowerCase() !== office) continue;
    updated = String(r[5] || '');
    out.push({first: String(r[1] || '').trim(), last: String(r[2] || '').trim(),
              status: String(r[3] || '').trim(),
              date: r[4] instanceof Date ? Utilities.formatDate(r[4], 'America/Chicago', 'M/d') : String(r[4] || '')});
  }
  return {ok: true, updated: updated, people: out};
}

// ---------------------------------------------------------------- the board
//
// The onboarding board, read and written straight from here rather than
// through the office's computer. A job queue is right for WORK (signing in to
// Sterling, filling Apex); it is wrong for looking at a list, because nobody
// waits three minutes to see a board. Reading a sheet is what Apps Script is
// for.

function _boardTab(office) {
  var set = _admSettings(office);
  if (!set.sheet) return null;
  var book;
  try { book = SpreadsheetApp.openById(set.sheet); } catch (err) { return null; }
  return book.getSheetByName(BOARD_TAB);
}

function _boardRows(sh) {
  var grid = sh.getDataRange().getValues();
  if (grid.length < BOARD_FIRST_ROW) return {head: [], rows: []};
  var head = grid[BOARD_HEADER_ROW - 1].map(function (h) { return String(h).trim(); });
  var rows = [];
  for (var i = BOARD_FIRST_ROW - 1; i < grid.length; i++) {
    var r = {}, any = false;
    for (var c = 0; c < head.length; c++) {
      if (!head[c]) continue;
      r[head[c]] = String(grid[i][c] == null ? '' : grid[i][c]).trim();
      if (r[head[c]]) any = true;
    }
    if (any && (r['Name'] || r['Last Name'])) { r.__row = i + 1; rows.push(r); }
  }
  return {head: head, rows: rows};
}

function _boardWeek(office, a) {
  var sh = _boardTab(office);
  if (!sh) {
    return {ok: false, error: "This office has no onboarding board yet. " +
            "Ask Lucy's team to switch it on."};
  }
  var got = _boardRows(sh);
  var want = String(a.week || '').trim();
  var weeks = {}, out = [];
  got.rows.forEach(function (r) {
    var w = r['Week of'] || '';
    if (w) weeks[w] = true;
    if (!want || w === want) out.push(r);
  });
  var list = Object.keys(weeks).sort(function (x, y) {
    return new Date(y) - new Date(x);        // newest first
  });
  return {ok: true, week: want || list[0] || '', weeks: list,
          columns: got.head, people: out};
}

// Mark somebody off for the week, or put them back. The ROW STAYS either way:
// hidden from the board and the printout, still there to answer what happened
// to a person months later.
function _boardMark(office, a) {
  var sh = _boardTab(office);
  if (!sh) return {ok: false, error: 'No onboarding board for this office.'};
  var got = _boardRows(sh);
  var col = got.head.indexOf('Terminated');
  if (col < 0) return {ok: false, error: "The board has no 'Terminated' column."};
  var want = {};
  (a.names || []).forEach(function (n) { want[_boardKey(n)] = true; });
  var off = String(a.action || 'terminate') !== 'restore';
  var stamp = off ? Utilities.formatDate(new Date(),
      Session.getScriptTimeZone(), 'MM/dd/yyyy') : '';
  // WHY they came off, beside the date (Megan, 2026-11-11). Written only on
  // the way out; putting somebody back clears it, so a restored row does not
  // keep a reason for a removal that was undone. An older tab without the
  // column still records the removal -- it just cannot say why.
  var whyCol = got.head.indexOf('Removed Because');
  var why = off ? String(a.reason || '') : '';
  var n = 0;
  got.rows.forEach(function (r) {
    if (a.week && r['Week of'] !== a.week) return;
    if (!want[_boardKey((r['Name'] || '') + ' ' + (r['Last Name'] || ''))]) return;
    if (off === !!r['Terminated']) return;            // already how they want it
    sh.getRange(r.__row, col + 1).setValue(stamp);
    if (whyCol >= 0) sh.getRange(r.__row, whyCol + 1).setValue(why);
    n++;
  });
  return {ok: true, changed: n};
}

// The one column the ICD owns: who goes on which printed sheet.
function _boardClassroom(office, a) {
  return _boardColumn(office, a, 'Classroom');
}

function _boardLocation(office, a) {
  // Where this person is working from (Megan, 2026-11-11). Typed in the panel
  // like the classroom: an office's locations are its own, and nothing we read
  // holds them.
  return _boardColumn(office, a, 'Location');
}

function _boardGender(office, a) {
  // Apex requires a gender and an ECO machine has no sales board to read one
  // from (Megan, 2026-11-10). Typed in the panel week over week, like the
  // classroom, because both change every week and neither is derivable.
  return _boardColumn(office, a, 'Gender');
}

function _boardColumn(office, a, colName) {
  // The one shape both of the ICD's own columns use. Writes only the cells it
  // was asked about, only on the week it was given, and only when the value
  // actually differs -- so a panel save never rewrites the whole column and
  // never touches another week.
  var sh = _boardTab(office);
  if (!sh) return {ok: false, error: 'No onboarding board for this office.'};
  var got = _boardRows(sh);
  var col = got.head.indexOf(colName);
  if (col < 0) return {ok: false, error: "The board has no '" + colName + "' column."};
  var want = {};
  Object.keys(a.assignments || {}).forEach(function (k) {
    want[_boardKey(k)] = String(a.assignments[k] || '').trim();
  });
  var n = 0;
  got.rows.forEach(function (r) {
    if (a.week && r['Week of'] !== a.week) return;
    var k = _boardKey((r['Name'] || '') + ' ' + (r['Last Name'] || ''));
    if (!(k in want) || r[colName] === want[k]) return;
    sh.getRange(r.__row, col + 1).setValue(want[k]);
    n++;
  });
  return {ok: true, changed: n};
}

function _boardKey(name) {
  return String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}


// READING IT FROM THE MACHINE is the same function the extension uses
// (_boardWeek) on the office-key path instead of an admin session. A step has
// to know what a cell already says before it can obey the on-only rule, and an
// unattended run has nobody to sign in. It is a read of this office's own
// board and nothing else, so it needs no separate implementation.
//
// ---------------------------------- the board, written by an office's MACHINE
//
// Everything above this line is the EXTENSION's half of the board: a person
// signed in, looking at a week, typing a classroom. These two are the other
// half -- an unattended run on the office's OWN computer, which is the whole
// point of LucyEco and the one thing the board could not do until now.
//
// WHY THEY HAVE TO EXIST (Megan, 2026-11-16: "we need Raf's fully running on
// HIS ECO machine, not the Lucys"). An office Mac has no Google access at all;
// it reaches these sheets only through this relay. So every onboarding step
// ran on a Lucy instead, which is why one office's board lived on shared
// machines signed in as somebody else -- and why Lucy 2, signed in as Carlos,
// once read 0 of 10 on Raf's people.
//
// THEY ARE ON THE OFFICE-KEY PATH, not the admin session: nobody is sitting
// there to sign in at 6:30am. doPost has already checked the key against THIS
// office before either is called, so an office can only ever seed or tick its
// own board -- the same rule the job queue has.
//
// WHAT THEY MAY NOT DO is as important as what they do. Neither one creates a
// tab, adds a column, deletes a row, clears a cell, or writes a column a
// person owns. A machine that can only add is a machine that cannot lose
// somebody's work.

// The columns an unattended run may write, and no others. Kept in step with
// board.py TICKS (the nine steps plus Showed Up); test_relay_board.py fails if
// the two lists drift. Classroom, Gender and Location are deliberately absent:
// nothing we read holds them, so a machine writing one would be inventing a
// fact that lands on a payroll record. Terminated and Removed Because are
// absent too -- taking somebody off the board is a person's call.
var BOARD_MACHINE_COLUMNS = ['Contact Added', 'BG Status', 'Digi Docs',
  'Onboarding Quizzes', 'Blue Ink', 'Headshot Photo', 'UID Request',
  'OV BG Status', 'Owner Submit', 'Added to APEX', 'Showed Up'];

// The two columns that carry an ANSWER rather than a tick, and how far along
// each answer is. Mirrors bg_check_sync parse.RANK through board.status_rank;
// test_relay_board.py fails if they drift. Blank, or a word not in here, is 0.
var BOARD_STATUS_COLUMNS = ['BG Status', 'OV BG Status', 'Showed Up'];

// `Showed Up` carries an ANSWER, not a tick, and is ranked on its own scale:
// blank = nobody has said yet (they may walk in on the Tuesday, so this must
// never read as "did not come"), 'No Show' = ApplicantStream was marked No by
// a person, a date = they turned up. A date outranks No Show deliberately --
// the Tuesday walk-in is the case the board exists to survive. Mirrors
// board.showed_up_rank; test_relay_board.py fails if they drift.
var BOARD_SHOWED_UP = 'Showed Up';
var BOARD_NO_SHOW = 'no show';

// The same green every other tick on this board is tinted, so a cell written
// from an office's own machine looks no different from one written by a Lucy.
// board.py GREEN is the same colour as fractions (0.71, 0.87, 0.66).
var BOARD_GREEN = '#b5dea8';
var BOARD_STATUS_RANK = {
  'sent': 1, 'taken - pending': 2, 'review': 3, 'complete': 4,
  'passed': 5, 'failed': 5, 'unperformable': 5
};

function _boardRank(text, column) {
  var want = String(text == null ? '' : text).trim().toLowerCase();
  if (column === BOARD_SHOWED_UP) {
    if (!want) return 0;
    return want === BOARD_NO_SHOW ? 1 : 2;
  }
  if (!want || want === 'not sent') return 0;
  return BOARD_STATUS_RANK[want] || 0;
}

// ADD THIS WEEK'S PEOPLE. Idempotent on purpose, because the seed runs every
// hour: a second pass adds whoever the calendar has gained since the last one
// and touches nothing else. Somebody brought on board at 2pm for a 3pm start
// is on the board by 3:30 without anybody opening a sheet.
//
// A ROW THAT IS ALREADY THERE IS NEVER REWRITTEN -- not even its email. A hand
// correction on the board beats what the calendar says, and the calendar is
// the thing that is usually out of date. That also means a person the ICD
// marked off does not come back: their row still exists, so they count as
// already there and are skipped.
//
// Only the identity columns are written. Every other column belongs to the
// step that earns it, and writing a blank would be this call claiming to know
// something it does not.
function _boardSeed(office, a) {
  var sh = _boardTab(office);
  if (!sh) return {ok: false, error: 'No onboarding board for this office.'};
  var week = String(a.week || '').trim();
  if (!week) return {ok: false, error: 'board_seed needs a week.'};
  var got = _boardRows(sh);
  if (!got.head.length) return {ok: false, error: 'The board has no header row.'};

  var here = {};
  got.rows.forEach(function (r) {
    if (String(r['Week of'] || '').trim() !== week) return;
    here[_boardKey((r['Name'] || '') + ' ' + (r['Last Name'] || ''))] = true;
  });

  var FIELDS = {first: 'Name', last: 'Last Name', email: 'Email',
                phone: 'Phone', start: 'Start'};
  var add = [], names = [], seen = {};
  (a.people || []).forEach(function (p) {
    var first = String(p.first || '').trim(), last = String(p.last || '').trim();
    if (!first && !last) return;
    var k = _boardKey(first + ' ' + last);
    if (here[k] || seen[k]) return;          // already on this week, or sent twice
    seen[k] = true;
    var line = [];
    for (var c = 0; c < got.head.length; c++) line.push('');
    var put = function (col, val) {
      var i = got.head.indexOf(col);
      if (i >= 0) line[i] = val;
    };
    put('Week of', week);
    Object.keys(FIELDS).forEach(function (f) {
      put(FIELDS[f], String(p[f] == null ? '' : p[f]).trim());
    });
    add.push(line);
    names.push((first + ' ' + last).trim());
  });
  if (!add.length) return {ok: true, added: 0, names: [], already: Object.keys(here).length};

  // APPENDED AFTER EVERY WEEK ALREADY ON THE TAB. One tab holds the weeks
  // stacked, so the new block goes at the bottom and no existing row moves.
  var at = sh.getLastRow() + 1;
  if (at < BOARD_FIRST_ROW) at = BOARD_FIRST_ROW;
  sh.getRange(at, 1, add.length, got.head.length).setValues(add);
  return {ok: true, added: add.length, names: names,
          already: Object.keys(here).length};
}

// TICK A STEP, or advance one of the two background-check answers.
//
// ON ONLY, like every other tick on this board: a cell that already says
// something is left exactly as it is, and a person who is NOT in the call is
// never cleared. A tick is evidence that something happened and nothing here
// is entitled to say it did not -- which is also why an unread step must send
// nothing at all rather than send a blank.
//
// The two status columns ADVANCE instead, and only forwards, so a late "Sent"
// email can never pull somebody back from Passed.
function _boardTick(office, a) {
  var sh = _boardTab(office);
  if (!sh) return {ok: false, error: 'No onboarding board for this office.'};
  var week = String(a.week || '').trim();
  if (!week) return {ok: false, error: 'board_tick needs a week.'};
  var colName = String(a.column || '').trim();
  if (BOARD_MACHINE_COLUMNS.indexOf(colName) < 0) {
    return {ok: false, error: "'" + colName + "' is not a column a machine " +
            'may write. The steps are: ' + BOARD_MACHINE_COLUMNS.join(', ')};
  }
  var got = _boardRows(sh);
  var col = got.head.indexOf(colName);
  if (col < 0) {
    return {ok: false, error: "The board has no '" + colName + "' column. If " +
            'it was renamed, rename it here too: this never guesses at a position.'};
  }
  var isStatus = BOARD_STATUS_COLUMNS.indexOf(colName) >= 0;

  // A tick carries no value, so the relay stamps the date rather than letting
  // a caller choose one: the useful fact is when WE saw it, in this sheet's
  // own time zone, and a machine with a wrong clock cannot write a wrong date.
  var stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(),
                                   'MM/dd/yyyy');
  var want = {};
  if (isStatus) {
    Object.keys(a.values || {}).forEach(function (k) {
      want[_boardKey(k)] = String(a.values[k] == null ? '' : a.values[k]).trim();
    });
  } else {
    (a.names || []).forEach(function (n) { want[_boardKey(n)] = stamp; });
  }

  var wrote = [], held = 0;
  got.rows.forEach(function (r) {
    if (String(r['Week of'] || '').trim() !== week) return;
    var k = _boardKey((r['Name'] || '') + ' ' + (r['Last Name'] || ''));
    if (!(k in want)) return;
    var val = want[k];
    if (!val) return;                                  // nothing to say
    var have = String(r[colName] || '').trim();
    if (have) {
      if (!isStatus) { held++; return; }                // written once, never again
      if (_boardRank(val, colName) <= _boardRank(have, colName)) {
        held++; return;                                  // forwards only
      }
    }
    var cell = sh.getRange(r.__row, col + 1);
    cell.setValue(val);
    cell.setBackground(BOARD_GREEN);
    wrote.push((r['Name'] || '') + ' ' + (r['Last Name'] || ''));
  });
  return {ok: true, column: colName, changed: wrote.length, names: wrote,
          left_alone: held};
}


function _admApexWeek(sess, office, a) {
  // "Run new starts -> Apex for the week of X" on the office's OWN computer:
  // it holds that office's Blue Ink key and its Apex session, and the admin
  // holds neither (Megan 2026-11-06). The admin says WHICH WEEK; nothing about
  // who is in it is decided here -- the office's computer reads that off its
  // own training calendar, so a stale or edited list cannot be posted in.
  var week = String(a.week_start || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(week)) {
    return {ok: false, error: 'week_start must look like 2026-11-02.'};
  }
  // ONE AT A TIME, PER OFFICE. This job CREATES PAYROLL RECORDS, so a second
  // press while the first is still running must not queue a second run --
  // both would read the same calendar and both would try to create the same
  // people. The duplicate check on the Apex side is the second line of
  // defence; not queuing it twice is the first.
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  if (sh) {
    var rows = sh.getDataRange().getValues();
    for (var i = 1; i < rows.length; i++) {
      var r = rows[i];
      if (String(r[OJ.OFFICE]).trim().toLowerCase() !== office) continue;
      if (String(r[OJ.KIND]) !== 'apex_week') continue;
      if (r[OJ.RESULT_AT]) continue;                      // finished, fine
      var p = {};
      try { p = JSON.parse(String(r[OJ.PAYLOAD] || '{}')); } catch (err) {}
      if (String(p.week_start || '') !== week) continue;
      return {ok: true, job_id: String(r[OJ.ID]), already_running: true,
              status: String(r[OJ.STATUS])};
    }
  }
  var o = _admOffice(sess, office);
  return _officeJobEnqueue({office: office, kind: 'apex_week', mode: o.mode,
                            payload: {week_start: week, by: sess.username}});
}

// VOLUME CHECK (Megan 2026-11-08): a send much bigger than this office's usual
// needs a second yes. Usual = people actually SENT (not test runs) per day over
// the last 14 days, counting only days that had a send. Big = more than
// BIG_TIMES that, and more than BIG_FLOOR people.
var BIG_TIMES = 3, BIG_FLOOR = 10;
function _admUsualPerDay(office) {
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  if (!sh) return 0;
  var rows = sh.getDataRange().getValues(), byDay = {};
  var cutoff = new Date(Date.now() - 14 * 86400000);
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (String(r[OJ.OFFICE]).trim().toLowerCase() !== office) continue;
    if (!(r[OJ.RESULT_AT] instanceof Date) || r[OJ.RESULT_AT] < cutoff) continue;
    var res = {};
    try { res = JSON.parse(String(r[OJ.RESULT] || '{}')); } catch (err) {}
    if (res.status !== 'sent') continue;
    var d = Utilities.formatDate(r[OJ.RESULT_AT], 'America/Chicago', 'yyyy-MM-dd');
    byDay[d] = (byDay[d] || 0) + (res.sent || []).length;
  }
  var days = Object.keys(byDay);
  if (!days.length) return 0;
  return days.reduce(function (t, d) { return t + byDay[d]; }, 0) / days.length;
}

function _admAlready(office) {
  // Who this office's computer already SENT (not test runs), last 14 days.
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  var out = {};
  if (!sh) return {ok: true, sent: out};
  var rows = sh.getDataRange().getValues();
  var cutoff = new Date(Date.now() - 14 * 86400000);
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (String(r[OJ.OFFICE]).trim().toLowerCase() !== office) continue;
    if (!(r[OJ.RESULT_AT] instanceof Date) || r[OJ.RESULT_AT] < cutoff) continue;
    var res = {};
    try { res = JSON.parse(String(r[OJ.RESULT] || '{}')); } catch (err) {}
    if (res.status !== 'sent') continue;
    var payload = {};
    try { payload = JSON.parse(String(r[OJ.PAYLOAD] || '{}')); } catch (err) {}
    var md = (r[OJ.RESULT_AT].getMonth() + 1) + '/' + r[OJ.RESULT_AT].getDate();
    (payload.people || []).forEach(function (p) {
      var e = String(p.email || '').trim().toLowerCase();
      if (e) out[e] = md;
    });
  }
  return {ok: true, sent: out};
}


// Lucy's read of one office's sends (the 6pm "not sent yet" alert,
// office_admin.bgc_alert): every job for the office answered since `since`
// (ISO), with who was in it and what came back. Read-only.
function _officeJobLog(q) {
  var office = String(q.office || '').trim().toLowerCase();
  var since = q.since ? new Date(String(q.since)) : new Date(Date.now() - 86400000);
  var sh = _book().getSheetByName(OFFICE_JOBS_TAB);
  var out = [];
  if (!office || !sh) return {ok: true, jobs: out};
  var rows = sh.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (String(r[OJ.OFFICE]).trim().toLowerCase() !== office) continue;
    if (!(r[OJ.QUEUED] instanceof Date) || r[OJ.QUEUED] < since) continue;
    var payload = {}, res = {};
    try { payload = JSON.parse(String(r[OJ.PAYLOAD] || '{}')); } catch (err) {}
    try { res = JSON.parse(String(r[OJ.RESULT] || '{}')); } catch (err) {}
    out.push({job_id: String(r[OJ.ID]), status: String(r[OJ.STATUS]), mode: String(r[OJ.MODE]),
              queued_at: r[OJ.QUEUED].toISOString(), people: payload.people || [], result: res});
  }
  return {ok: true, jobs: out};
}
