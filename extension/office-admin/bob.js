// The 6pm BOB-call nudge, on the page the calls get marked on.
//
// Megan, 2026-11-18: "we want to build a daily nudge / alert if BOB calls
// aren't made by 6pm local time -- should pop up on app stream and send DM in
// slack". The DM half is automations/second_round_contacts/bob_nudge.py; this
// is the half that pops up.
//
// IT DOES NOT READ THE CALENDAR. bob_nudge does, through a real login, with
// rules that took a day of probing -- which rows turned up, which four marks
// count as answered, which of the calendar's several same-headed tables is
// the right one. Working that out again here would be two answers to one
// question, and the day they disagree the card tells an office it owes calls
// the DM says are made. So the nudge publishes what it read and this asks the
// relay for it ('bob_nudge'). The only thing read off the page here is the
// account number in the page header, which is how we know WHICH office this
// is -- and it is read with its own regex rather than through LucyOffered,
// because that module keeps the document it is reading in a variable and
// content.js may be part-way through another account's calendar in a hidden
// frame when this timer fires.
//
// FAIL QUIET, NEVER LOUD. Nothing is drawn unless the relay says `nudge:
// true`. No snapshot, a stale one, before the office's own 6pm, the button
// already pressed, signed out, an error of any kind: nothing appears at all,
// and the reason goes to the console. A card that shows up when the calls ARE
// made, or when the read failed, is the one that teaches people to dismiss
// the real ones.
(function () {
  'use strict';
  if (window.__lucyBobNudge) return;
  window.__lucyBobNudge = true;

  // SWITCHED OFF, like the rest of the chain. Megan, 2026-11-19: "don't take
  // anything live yet for actual posting - I want this all built out first".
  // The DM half's LaunchAgent is disarmed for the same reason, so the half
  // that pops up does not go live on a `git pull` either. Flip this to true
  // when the chain is signed off -- it is the only change needed.
  //
  // TO SEE IT FIRST WITHOUT ARMING IT (the preview rule in CLAUDE.md): in
  // chrome://extensions -> Lucy BG✔️ Send -> service worker, run
  //   chrome.storage.local.set({bobPreview: true})
  // and reload the ApplicantStream tab. One computer, nobody else's. The same
  // line with `false` puts it back.
  var ARMED = false;

  var CARD = 'lucy-bob-card';
  // An ApplicantStream tab sits open all day, so a page loaded at 4pm would
  // never see 6pm arrive. Asked again every 20 minutes: one small relay read,
  // and the nudge itself only refreshes hourly.
  var RECHECK_MS = 20 * 60 * 1000;
  var SHOW_NAMES = 6;

  var live = function () { return !!(chrome.runtime && chrome.runtime.id); };
  var ask = function (call, extra) {
    return new Promise(function (r) {
      if (!live()) { r({ok: false, error: 'extension reloaded'}); return; }
      try {
        chrome.runtime.sendMessage({type: 'relay', call: call, extra: extra},
                                   function (out) { r(out || {ok: false, error: 'no answer'}); });
      } catch (e) { r({ok: false, error: String(e && e.message)}); }
    });
  };
  var esc = function (s) {
    return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  };
  var quiet = function (why) { console.debug('[lucy] BOB nudge: ' + why); };

  // The account number in the page's own header -- "Office ID: 11280" (a
  // call-centre login), "(Account No: 21151)" (an owner's own login), or the
  // V2 picker's "(#11280 - ...)". Same three shapes offered.js matches; the
  // CALENDAR rules are deliberately not duplicated here.
  function pageAccount() {
    var t = (document.body && document.body.innerText) || '';
    var m = t.match(/Office ID:\s*(\d+)/) || t.match(/Account No:\s*(\d+)/i) ||
            t.match(/\(#(\d+)\s*-/);
    return m ? m[1] : '';
  }

  // WHICH OFFICE IS THIS. The page's account number when it has one, matched
  // against the admin's offices; an admin with exactly ONE office needs no
  // number, because there is no other office it could be about. Anything
  // ambiguous -- a number on none of their offices, a number on two of them,
  // several offices and no number -- draws nothing. Showing one office's
  // names to another office's admin is both a privacy problem and the fastest
  // way to make the card worthless.
  function pickOffice(me) {
    var offices = (me && me.offices) || [];
    if (!offices.length) return null;
    var nums = function (v) { return String(v || '').match(/\d+/g) || []; };
    var page = pageAccount();
    if (page) {
      var hit = offices.filter(function (o) { return nums(o.appstream).indexOf(page) >= 0; });
      return hit.length === 1 ? hit[0] : null;
    }
    return offices.length === 1 ? offices[0] : null;
  }

  // Dismissed for the day, per office: {raf: '2026-11-24'}. Pressing the
  // button counts as dismissing it too -- the relay would stop answering
  // `nudge: true` anyway, but not before the next 20-minute ask, and a card
  // that reappears after you have answered it reads as broken.
  function seen() {
    return new Promise(function (r) {
      if (!live()) { r({}); return; }
      chrome.storage.local.get(['bobSeen'], function (st) { r((st && st.bobSeen) || {}); });
    });
  }
  function markSeen(office, day) {
    if (!live()) return;
    seen().then(function (map) {
      map[office] = day;
      // Only today's answers are worth keeping; yesterday's would pile up one
      // key per office per day forever.
      Object.keys(map).forEach(function (k) { if (map[k] !== day) delete map[k]; });
      chrome.storage.local.set({bobSeen: map});
    });
  }

  function remove() {
    var el = document.getElementById(CARD);
    if (el) el.remove();
  }

  // Where the marking happens: the calendar's Second Interviews table
  // (p=102). The same page bob_nudge opens on an office's own machine, and
  // the reason it is p=102 and not the Retention report (p=701) is that the
  // report has nothing on it to mark.
  function secondRoundsUrl() {
    var tok = (location.href.match(/rqst=([A-Z0-9-]+)/i) || [])[1] || '';
    if (/applicantstream\.com/i.test(location.hostname) && tok) {
      return location.origin + location.pathname + '?rqst=' + tok + '&p=102';
    }
    return 'https://www.applicantstream.com/main.html?p=102';
  }

  function draw(office, info) {
    remove();
    var names = (info.names || []).slice(0, SHOW_NAMES);
    var more = (info.names || []).length - names.length;
    var n = info.count || (info.names || []).length;
    var card = document.createElement('div');
    card.id = CARD;
    card.innerHTML =
      '<div class="lucy-bob-head">' +
        '<b>📞 ' + n + ' BOB call' + (n === 1 ? '' : 's') + ' not marked yet</b>' +
        '<button class="lucy-bob-x" title="Hide this until tomorrow">✕</button>' +
      '</div>' +
      '<div class="lucy-bob-body">' +
        '<p class="lucy-bob-why">It is past 6pm. At 7pm anyone still unmarked comes ' +
          'out of your reception contacts.</p>' +
        (names.length ? '<ul class="lucy-bob-names">' + names.map(function (x) {
            return '<li>' + esc(x) + '</li>';
          }).join('') + (more > 0 ? '<li>and ' + more + ' more</li>' : '') + '</ul>' : '') +
        '<p class="lucy-bob-where">Each one gets <b>BOB</b> (with the start date), ' +
          '<b>Declined</b>, <b>Disqualified</b> or <b>LM</b> on ' +
          '<a class="lucy-bob-link" href="' + esc(secondRoundsUrl()) + '">' +
          'today\'s second interviews</a>.</p>' +
        '<button class="lucy-bob-go">✅ I\'ve made today\'s BOB calls</button>' +
        '<p class="lucy-bob-note">Press that once they are all marked and scheduled. ' +
          'Your daily update waits for it, so it is never posted with the answers missing.</p>' +
        '<div class="lucy-bob-msg"></div>' +
      '</div>';
    document.body.appendChild(card);

    card.querySelector('.lucy-bob-x').onclick = function () {
      markSeen(office.office, info.day);
      remove();
    };
    var go = card.querySelector('.lucy-bob-go');
    go.onclick = function () {
      go.disabled = true;
      go.textContent = 'Saving…';
      ask('bob_done', {office: office.office}).then(function (out) {
        if (!out || !out.ok) {
          // SAY SO AND LEAVE THE BUTTON. A press that silently did not save
          // means an office sits all evening waiting for an update that is
          // still held, with nothing on screen saying why.
          go.disabled = false;
          go.textContent = '✅ I\'ve made today\'s BOB calls';
          card.querySelector('.lucy-bob-msg').innerHTML =
            '<div class="lucy-bob-err">That did not save' +
            (out && out.error ? ' (' + esc(out.error) + ')' : '') +
            ' — press it again.</div>';
          return;
        }
        markSeen(office.office, info.day);
        // THE WHOLE CARD ANSWERS, not just a line under it. Leaving "4 BOB
        // calls not marked yet" and the 7pm warning standing over a green
        // tick is a card that says two things at once, and the one it says
        // loudest is the one that is no longer true.
        card.querySelector('.lucy-bob-head b').textContent = '✅ Thanks — that is marked';
        card.querySelector('.lucy-bob-body').innerHTML =
          '<div class="lucy-bob-ok">Today\'s BOB calls are marked done' +
          (out.already ? ' (they already were)' : '') +
          '. Your daily update can post.</div>';
        setTimeout(remove, 8000);
      });
    };
  }

  function armed() {
    if (ARMED) return Promise.resolve(true);
    return new Promise(function (r) {
      if (!live()) { r(false); return; }
      chrome.storage.local.get(['bobPreview'], function (st) { r(!!(st && st.bobPreview)); });
    });
  }

  async function check() {
    if (!live()) return;
    if (!(await armed())) { quiet('switched off (ARMED is false)'); return; }
    // NOT OVER THE TOP OF SOMEBODY'S WORK. The background-check panel is open
    // because the admin is in the middle of something; this waits for the
    // next ask rather than landing on it.
    if (document.getElementById('lucy-oa-panel')) { quiet('the BGC panel is open'); return; }
    if (document.getElementById(CARD)) return;
    var me = await ask('whoami');
    // Signed out is not a thing to pop up about: this card is unasked-for, so
    // a sign-in demand on top of a page nobody asked it about is noise. The
    // Lucy icon says so when they open it.
    if (!me || !me.ok) { quiet('not signed in (' + ((me && me.error) || '?') + ')'); return; }
    var office = pickOffice(me);
    if (!office) { quiet("couldn't tell which of this admin's offices this page is"); return; }
    var info = await ask('bob_nudge', {office: office.office});
    if (!info || !info.ok) { quiet('the relay could not answer (' + ((info && info.error) || '?') + ')'); return; }
    if (!info.nudge) { quiet(office.office + ': saying nothing — ' + (info.why || 'nothing to nudge')); return; }
    var map = await seen();
    if (map[office.office] === info.day) { quiet('already answered today'); return; }
    draw(office, info);
  }

  // document_idle still beats the rows filling in on some ApplicantStream
  // pages; a few seconds costs nothing on a card nobody is waiting for.
  setTimeout(check, 4000);
  setInterval(check, RECHECK_MS);
})();
