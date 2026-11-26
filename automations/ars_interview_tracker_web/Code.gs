/**
 * ARS Interview Tracker - web app backed by this Google Sheet, with its own usernames and passwords.
 * @OnlyCurrentDoc
 *
 * Deploy: Deploy > New deployment > Web app
 *   Execute as: Me
 *   Who has access: Anyone   (or "Anyone with Google account" if "Anyone" is not offered)
 * Nobody sees data without signing in. Logins are managed in the app's Users tab (Admins only)
 * and stored in the "Users" sheet as salted password hashes (never the passwords themselves).
 */

var SH = { I: 'Interviews', O: 'Offices', N: 'Interviewers', A: 'AdGroups', U: 'Users' };
var I_HEAD = ['id','office','Date 1st Rd','1st Round Interviewer','Full Name','Qualify','Reasons','Answer Call',
  'Booked to 2nd Rd','Date 2nd Rd','Showed Up to 2nd Round','Offered Position','BOB','Ad Title','Star Rating','updated','updated_by'];
var U_HEAD = ['username','name','role','active','salt','hash','lastLogin'];
var NCOL = I_HEAD.length;
var SESSION_SECONDS = 6 * 3600;   // sessions last 6 hours of inactivity
var HASH_ROUNDS = 300;

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('ARS Interview Tracker')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/* ---------- sheets ---------- */
function ss_() { return SpreadsheetApp.getActiveSpreadsheet(); }
function sheet_(name, head) {
  var s = ss_().getSheetByName(name);
  if (!s) {
    s = ss_().insertSheet(name);
    if (head) s.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold');
    s.setFrozenRows(1);
  }
  return s;
}
function interviews_() {
  var s = sheet_(SH.I, I_HEAD);
  s.getRange('C:C').setNumberFormat('@');
  s.getRange('J:J').setNumberFormat('@');
  return s;
}
function tz_() { return ss_().getSpreadsheetTimeZone(); }
function cellText_(v) {
  if (v instanceof Date) return Utilities.formatDate(v, tz_(), 'yyyy-MM-dd');
  if (v === null || v === undefined) return '';
  return String(v);
}
function dateText_(v) {
  if (v instanceof Date) return Utilities.formatDate(v, tz_(), 'yyyy-MM-dd');
  var s = String(v || '').trim();
  var m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return m[1] + '-' + ('0' + m[2]).slice(-2) + '-' + ('0' + m[3]).slice(-2);
  m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
  if (m) return (m[3].length === 2 ? '20' + m[3] : m[3]) + '-' + ('0' + m[1]).slice(-2) + '-' + ('0' + m[2]).slice(-2);
  return s;
}
function readAll_() {
  var s = interviews_(), n = s.getLastRow() - 1;
  return n > 0 ? s.getRange(2, 1, n, NCOL).getValues() : [];
}
function withLock_(fn) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try { return fn(); } finally { lock.releaseLock(); }
}
function slug_(s) {
  return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'office';
}
function offices_() {
  var s = sheet_(SH.O, ['id', 'name']), n = s.getLastRow() - 1;
  return n > 0 ? s.getRange(2, 1, n, 2).getValues().filter(function (r) { return r[0]; })
    .map(function (r) { return { id: String(r[0]), name: String(r[1]) }; }) : [];
}

/* ---------- users, passwords and sessions ---------- */
function users_() {
  var s = sheet_(SH.U, U_HEAD), n = s.getLastRow() - 1;
  if (n <= 0) return [];
  return s.getRange(2, 1, n, U_HEAD.length).getValues().filter(function (r) { return r[0]; }).map(function (r) {
    return { username: String(r[0]), name: String(r[1]), role: String(r[2]) === 'admin' ? 'admin' : 'interviewer',
      active: r[3] === true || String(r[3]).toUpperCase() === 'TRUE', salt: String(r[4]), hash: String(r[5]), lastLogin: Number(r[6]) || 0 };
  });
}
function writeUsers_(list) {
  var s = sheet_(SH.U, U_HEAD);
  if (s.getLastRow() > 1) s.getRange(2, 1, s.getLastRow() - 1, U_HEAD.length).clearContent();
  if (list.length) s.getRange(2, 1, list.length, U_HEAD.length).setValues(list.map(function (u) {
    return [u.username, u.name, u.role, u.active, u.salt, u.hash, u.lastLogin || ''];
  }));
}
function pub_(u) { return { username: u.username, name: u.name, role: u.role, active: u.active, lastLogin: u.lastLogin || 0 }; }
function hex_(bytes) { return bytes.map(function (b) { return ('0' + (b & 255).toString(16)).slice(-2); }).join(''); }
function rand_(n) { var s = ''; while (s.length < n) s += Utilities.getUuid().replace(/-/g, ''); return s.slice(0, n); }
function hash_(salt, pw) {
  var h = salt + '|' + pw;
  for (var i = 0; i < HASH_ROUNDS; i++) h = hex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, h + '|' + salt, Utilities.Charset.UTF_8));
  return h;
}
function authErr_(m) { return new Error('AUTH: ' + m); }
function checkPw_(pw) { if (String(pw || '').length < 8) throw new Error('The password needs at least 8 characters.'); }
function checkUsername_(u) { if (!/^[a-z0-9._-]{3,}$/.test(u)) throw new Error('Usernames need 3+ letters, numbers, dots, dashes or underscores.'); }
function cache_() { return CacheService.getScriptCache(); }
function newSession_(u) {
  var t = rand_(48);
  cache_().put('s_' + t, u.username, SESSION_SECONDS);
  return t;
}
function endSessionsFor_(username) {
  var c = cache_(), key = 'u_' + username, list = JSON.parse(c.get(key) || '[]');
  list.forEach(function (t) { c.remove('s_' + t); });
  c.remove(key);
}
function trackSession_(username, token) {
  var c = cache_(), key = 'u_' + username, list = JSON.parse(c.get(key) || '[]');
  list.push(token); c.put(key, JSON.stringify(list.slice(-20)), SESSION_SECONDS);
}
/** Returns the signed-in user for a token, or throws AUTH. */
function who_(token) {
  var username = token ? cache_().get('s_' + token) : null;
  if (!username) throw authErr_('Please sign in.');
  var u = users_().filter(function (x) { return x.username === username; })[0];
  if (!u || !u.active) { cache_().remove('s_' + token); throw authErr_('Your account is disabled. Ask an Admin.'); }
  cache_().put('s_' + token, username, SESSION_SECONDS); // keep the session alive while in use
  return u;
}
function admin_(token) { var u = who_(token); if (u.role !== 'admin') throw new Error('Only Admins can do this.'); return u; }

/* ---------- public (no sign-in) ---------- */
function needsSetup() { return users_().length === 0; }

function setupAdmin(name, username, pw) {
  return withLock_(function () {
    if (users_().length) throw new Error('Setup is already done. Sign in instead.');
    username = String(username || '').trim().toLowerCase();
    if (!name) throw new Error('Enter your name.');
    checkUsername_(username); checkPw_(pw);
    var salt = rand_(32), u = { username: username, name: String(name).trim(), role: 'admin', active: true, salt: salt, hash: hash_(salt, pw), lastLogin: Date.now() };
    writeUsers_([u]);
    var t = newSession_(u); trackSession_(u.username, t);
    return { token: t, user: pub_(u) };
  });
}

function login(username, pw) {
  username = String(username || '').trim().toLowerCase();
  var c = cache_(), failKey = 'f_' + username, fails = Number(c.get(failKey) || 0);
  if (fails >= 5) throw authErr_('Too many wrong attempts. Wait 10 minutes and try again.');
  var list = users_(), u = list.filter(function (x) { return x.username === username; })[0];
  if (!u || u.hash !== hash_(u.salt, pw)) {
    c.put(failKey, String(fails + 1), 600);
    throw authErr_('Wrong username or password.');
  }
  if (!u.active) throw authErr_('Your account is disabled. Ask an Admin.');
  c.remove(failKey);
  withLock_(function () {
    var l = users_(); l.forEach(function (x) { if (x.username === u.username) x.lastLogin = Date.now(); }); writeUsers_(l);
  });
  var t = newSession_(u); trackSession_(u.username, t);
  return { token: t, user: pub_(u) };
}

function logout(token) { if (token) cache_().remove('s_' + token); return true; }

/* ---------- signed-in API (first argument is always the session token) ---------- */
function bootstrap(token) {
  var u = who_(token);
  var ns = sheet_(SH.N, ['Interviewer']), nn = ns.getLastRow() - 1;
  var ints = nn > 0 ? ns.getRange(2, 1, nn, 1).getValues().map(function (r) { return String(r[0]).trim(); }).filter(String) : [];
  var as = sheet_(SH.A, ['key', 'label']), an = as.getLastRow() - 1, adMap = {};
  if (an > 0) as.getRange(2, 1, an, 2).getValues().forEach(function (r) { if (r[0]) adMap[String(r[0])] = String(r[1]); });
  return { user: pub_(u), offices: offices_(), ints: ints, adMap: adMap };
}

function getRows(token, officeId) {
  who_(token);
  var out = [];
  readAll_().forEach(function (r) {
    if (String(r[1]) !== officeId || !r[0]) return;
    out.push([String(r[0]), dateText_(r[2]), cellText_(r[3]), cellText_(r[4]), cellText_(r[5]), cellText_(r[6]), cellText_(r[7]),
      cellText_(r[8]), dateText_(r[9]), cellText_(r[10]), cellText_(r[11]), cellText_(r[12]), cellText_(r[13]), cellText_(r[14]), Number(r[15]) || 0]);
  });
  return out;
}

/** row = [id, b,d,e,f,g,h,i,j,k,l,m,n,p, t] */
function saveRow(token, officeId, row) {
  var me = who_(token);
  return withLock_(function () {
    var s = interviews_();
    var vals = [String(row[0]), officeId].concat(row.slice(1, 14).map(function (v) { return v == null ? '' : String(v); }))
      .concat([Number(row[14]) || Date.now(), me.username]);
    var hits = s.getRange('A:A').createTextFinder(String(row[0])).matchEntireCell(true).findAll();
    var hit = hits.filter(function (c) { return c.getRow() > 1 && String(s.getRange(c.getRow(), 2).getValue()) === officeId; })[0];
    if (hit) s.getRange(hit.getRow(), 1, 1, NCOL).setValues([vals]);
    else s.appendRow(vals);
    return true;
  });
}

function importRows(token, officeId, officeName, rows, mode, first) {
  var me = admin_(token);
  return withLock_(function () {
    ensureOffice_(officeId, officeName);
    var s = interviews_(), all = readAll_();
    if (mode === 'replace' && first) {
      var keep = all.filter(function (r) { return String(r[1]) !== officeId; });
      if (all.length) s.getRange(2, 1, all.length, NCOL).clearContent();
      if (keep.length) s.getRange(2, 1, keep.length, NCOL).setValues(keep);
      all = keep;
    }
    var keys = {};
    all.forEach(function (r) {
      if (String(r[1]) === officeId) keys[[dateText_(r[2]), String(r[4]).trim().toLowerCase(), String(r[3]).trim().toLowerCase()].join('|')] = 1;
    });
    var now = Date.now(), add = [], skipped = 0;
    rows.forEach(function (r, i) {
      var k = [r[0] || '', String(r[2] || '').trim().toLowerCase(), String(r[1] || '').trim().toLowerCase()].join('|');
      if (mode === 'add' && keys[k]) { skipped++; return; }
      keys[k] = 1;
      var id = now.toString(36) + i.toString(36) + Math.random().toString(36).slice(2, 6);
      add.push([id, officeId].concat(r.slice(0, 13).map(function (v) { return v == null ? '' : String(v); })).concat([now, me.username]));
    });
    if (add.length) s.getRange(s.getLastRow() + 1, 1, add.length, NCOL).setValues(add);
    return { added: add.length, skipped: skipped };
  });
}

function ensureOffice_(id, name) {
  if (offices_().some(function (o) { return o.id === id; })) return;
  sheet_(SH.O, ['id', 'name']).appendRow([id, name || id]);
}
function addOffice(token, name) {
  admin_(token);
  name = String(name || '').trim(); if (!name) throw new Error('Enter a name.');
  var id = slug_(name);
  withLock_(function () { ensureOffice_(id, name); });
  return { id: id, name: name, offices: offices_() };
}
function deleteOffice(token, id) {
  admin_(token);
  return withLock_(function () {
    var s = interviews_(), all = readAll_();
    var keep = all.filter(function (r) { return String(r[1]) !== id; });
    if (all.length) s.getRange(2, 1, all.length, NCOL).clearContent();
    if (keep.length) s.getRange(2, 1, keep.length, NCOL).setValues(keep);
    var os = sheet_(SH.O, ['id', 'name']), ol = offices_().filter(function (o) { return o.id !== id; });
    if (os.getLastRow() > 1) os.getRange(2, 1, os.getLastRow() - 1, 2).clearContent();
    if (ol.length) os.getRange(2, 1, ol.length, 2).setValues(ol.map(function (o) { return [o.id, o.name]; }));
    return offices_();
  });
}
function saveInterviewers(token, list) {
  admin_(token);
  return withLock_(function () {
    var s = sheet_(SH.N, ['Interviewer']);
    if (s.getLastRow() > 1) s.getRange(2, 1, s.getLastRow() - 1, 1).clearContent();
    if (list.length) s.getRange(2, 1, list.length, 1).setValues(list.map(function (n) { return [n]; }));
    return list;
  });
}

/* ---------- user management (Admins) ---------- */
function listUsers(token) { admin_(token); return users_().map(pub_); }

function saveUser(token, u) {
  var me = admin_(token);
  return withLock_(function () {
    var list = users_(), username = String(u.username || '').trim().toLowerCase();
    var x = list.filter(function (y) { return y.username === username; })[0];
    if (u.isNew) {
      if (x) throw new Error('The username "' + username + '" is taken.');
      checkUsername_(username);
      if (!u.name) throw new Error("Enter the person's name.");
      checkPw_(u.password);
      var salt = rand_(32);
      list.push({ username: username, name: String(u.name).trim(), role: u.role === 'admin' ? 'admin' : 'interviewer', active: true, salt: salt, hash: hash_(salt, u.password), lastLogin: 0 });
    } else {
      if (!x) throw new Error('That user no longer exists.');
      if (u.role && x.username === me.username && u.role !== 'admin') throw new Error("You can't remove your own Admin role.");
      if (u.active === false && x.username === me.username) throw new Error("You can't disable your own account.");
      if (u.role) x.role = u.role === 'admin' ? 'admin' : 'interviewer';
      if (typeof u.active === 'boolean') { x.active = u.active; if (!u.active) endSessionsFor_(x.username); }
      if (u.password) { checkPw_(u.password); x.salt = rand_(32); x.hash = hash_(x.salt, u.password); if (x.username !== me.username) endSessionsFor_(x.username); }
      if (u.name) x.name = String(u.name).trim();
    }
    if (!list.some(function (y) { return y.role === 'admin' && y.active; })) throw new Error('There must be at least one active Admin.');
    writeUsers_(list);
    return list.map(pub_);
  });
}

function deleteUser(token, username) {
  var me = admin_(token);
  if (username === me.username) throw new Error("You can't delete yourself.");
  return withLock_(function () {
    var list = users_().filter(function (u) { return u.username !== username; });
    writeUsers_(list); endSessionsFor_(username);
    return list.map(pub_);
  });
}

function changePassword(token, oldPw, newPw) {
  var me = who_(token);
  return withLock_(function () {
    var list = users_(), x = list.filter(function (y) { return y.username === me.username; })[0];
    if (x.hash !== hash_(x.salt, oldPw)) throw new Error('Your current password is wrong.');
    checkPw_(newPw); x.salt = rand_(32); x.hash = hash_(x.salt, newPw);
    writeUsers_(list);
    return true;
  });
}

/* ---------- Interviewers Retention (Raf 2026-11-20) ----------
 * A Lucy writes the daily Interviewers Retention report (the 4 tables of the
 * 6 PM email) into the 'Retention Report' tab as JSON, split over column A
 * (automations/interviewers_retention/web_export.py). Nobody edits that tab by
 * hand; this only reads it. */
var RET_TAB = 'Retention Report';
function getRetention(token) {
  who_(token);
  var s = ss_().getSheetByName(RET_TAB);
  if (!s || s.getLastRow() < 2) return '';
  return s.getRange(2, 1, s.getLastRow() - 1, 1).getValues()
    .map(function (r) { return String(r[0] || ''); }).join('');
}
