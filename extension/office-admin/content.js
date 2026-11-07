// On an ApplicantStream calendar: a "Send background checks" button. It reads
// today's Offer Position = Yes rows off THIS page (offered.js), marks who
// already got one, and sends the ticked people to the office's computer,
// which signs in to Sterling and bulk-uploads them (sterling_send.py).
(function () {
  'use strict';
  if (window.__lucyOfficeAdmin) return;
  window.__lucyOfficeAdmin = true;

  // After Lucy is updated, a tab opened before the update loses its link to
  // the extension (chrome.runtime goes away): say "refresh", don't just fail.
  const STALE = 'Lucy was just updated — refresh this page (⌘R / Ctrl+R) and try again.';
  const live = () => !!(chrome.runtime && chrome.runtime.id);
  const ask = (call, extra) => new Promise(r => {
    if (!live()) { r({ok: false, error: STALE}); return; }
    try { chrome.runtime.sendMessage({type: 'relay', call, extra}, out => r(out || {ok: false, error: STALE})); }
    catch (e) { r({ok: false, error: STALE}); }
  });
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let panel, pollTimer, tickTimer;

  // The floating button can be hidden with its ✕ (Megan 11/06: "not always
  // in the way"). The Lucy icon's "Send background checks" always works, and
  // its "Show the button on the calendar" brings this back.
  let hidden = false;
  if (live()) chrome.storage.local.get(['hideButton'], st => { hidden = !!st.hideButton; button(); });
  if (live()) chrome.storage.onChanged.addListener(ch => {
    if (!ch.hideButton) return;
    hidden = !!ch.hideButton.newValue;
    const b = document.getElementById('lucy-oa-btn');
    if (hidden && b) b.remove(); else button();
  });
  function button() {
    if (hidden || document.getElementById('lucy-oa-btn') || !LucyOffered.isCalendar()) return;
    const b = document.createElement('div');
    b.id = 'lucy-oa-btn';
    b.innerHTML = '<span class="lucy-oa-go">🛡️ Send background checks</span>' +
                  '<span class="lucy-oa-hide" title="Hide this button (the Lucy icon still works)">✕</span>';
    b.querySelector('.lucy-oa-go').addEventListener('click', open);
    b.querySelector('.lucy-oa-hide').addEventListener('click', e => {
      e.stopPropagation();
      if (live()) chrome.storage.local.set({hideButton: true}); else b.remove();
    });
    document.body.appendChild(b);
  }

  function shell(html) {
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'lucy-oa-panel';
      document.body.appendChild(panel);
    }
    panel.innerHTML = '<div class="lucy-oa-head"><b>🛡️ Background checks</b>' +
      '<button class="lucy-oa-x" title="Close">✕</button></div><div class="lucy-oa-body">' + html + '</div>';
    panel.querySelector('.lucy-oa-x').onclick = close;
  }

  function close() {
    clearInterval(pollTimer);
    clearInterval(tickTimer);
    if (panel) { panel.remove(); panel = null; }
  }

  async function open() {
    shell('<p>Checking who you are…</p>');
    const me = await ask('whoami');
    if (!me.ok) {
      shell('<p class="lucy-oa-err">' + esc(me.signed_out
        ? 'Sign in first: click the Lucy Office Admin icon at the top right of Chrome (once per computer).'
        : me.error) + '</p>');
      return;
    }
    // Which of this admin's offices is this calendar? By account number.
    const pageOffice = LucyOffered.officeId();
    const offices = me.offices || [];
    // An office can have several accounts ("11280, 24153"), all on one
    // Sterling. Only APPROVED ones count (the guard -- relay_admins --accounts).
    const nums = v => (String(v || '').match(/\d+/g) || []);
    const accts = o => nums(o.appstream).filter(n => nums(o.approved).includes(n));
    // No account number on the page = no send: the account IS the guard.
    const office = offices.find(o => pageOffice && accts(o).includes(pageOffice)) || null;
    if (!office) {
      shell('<p class="lucy-oa-err">' + (pageOffice
        ? 'This calendar is ApplicantStream account ' + esc(pageOffice) + ', which isn\'t approved for any of your offices, ' +
          'so nothing can be sent from it. Ask Megan if it should be.'
        : 'Couldn\'t tell which office this calendar is. Open the calendar for one office.') + '</p>');
      return;
    }
    if (!office.city || !office.state) {
      shell('<p class="lucy-oa-err">Set office ' + esc(office.office) + '\'s city and state first: click the Lucy Office Admin icon at the top right of Chrome.</p>');
      return;
    }
    // SEVERAL ACCOUNTS = ONE LIST, ONE SEND (Megan 11/06: same Sterling link
    // for all). Lucy opens each account's calendar in a hidden frame, reads it,
    // then puts the admin's ApplicantStream back on the account she was on.
    const list = accts(office);
    let people = [], problems = [];
    if (list.length > 1) {
      const order = [pageOffice].concat(list.filter(n => n !== pageOffice));
      for (let i = 0; i < order.length; i++) {
        shell('<p>Reading account <b>' + esc(order[i]) + '</b> (' + (i + 1) + ' of ' + order.length + ')…</p>' +
              '<p class="lucy-oa-note">Lucy is checking each of this office\'s calendars. Stay on this page.</p>');
        try {
          const got = order[i] === pageOffice ? await LucyOffered.read() : await readAccount(order[i]);
          got.forEach(p => { p.acct = order[i]; });
          people = people.concat(got);
        } catch (e) {
          problems.push({acct: order[i], why: e.message});
        }
      }
      try { await switchBack(pageOffice); } catch (e) { /* the next calendar load fixes it */ }
      // The same person on two calendars gets ONE invite.
      const seen = {};
      people = people.filter(p => {
        const k = (p.email || (p.first_name + '|' + p.last_name + '|' + p.phone)).toLowerCase();
        if (seen[k]) return false;
        seen[k] = 1;
        return true;
      });
    } else {
      shell('<p>Reading today\'s second interviews…</p>');
      try {
        people = await LucyOffered.read();
        people.forEach(p => { p.acct = pageOffice; });
      } catch (e) {
        shell('<p class="lucy-oa-err">Couldn\'t read this calendar: ' + esc(e.message) + '</p>');
        return;
      }
    }
    const already = (await ask('already', {office: office.office})).sent || {};
    render(office, people, already, list.length > 1 ? list : [pageOffice], problems);
  }

  // Another account's calendar, read in a hidden frame: switch the session's
  // office (the same p=104 newOfficeId switch the Indeed report uses), open the
  // calendar, prove it IS that account, read it.
  const BASE = location.origin + location.pathname;
  const TOK = (location.href.match(/rqst=([A-Z0-9-]+)/i) || [])[1] || '';
  function frameLoad(url, ms) {
    return new Promise((resolve, reject) => {
      let f = document.getElementById('lucy-oa-frame');
      if (!f) {
        f = document.createElement('iframe');
        f.id = 'lucy-oa-frame';
        document.body.appendChild(f);
      }
      const t = setTimeout(() => reject(new Error('the page took too long to open')), ms || 45000);
      f.onload = () => { clearTimeout(t); resolve(f.contentDocument); };
      f.src = url;
    });
  }
  const wait = ms => new Promise(r => setTimeout(r, ms));
  async function readAccount(acct) {
    if (!TOK) throw new Error('reload the calendar and try again');
    await frameLoad(BASE + '?p=104&rqst=' + TOK + '&newOfficeId=' + acct);
    const d = await frameLoad(BASE + '?rqst=' + TOK + '&p=102');
    for (let i = 0; i < 30 && !(LucyOffered.isCalendar(d) && LucyOffered.officeId(d)); i++) await wait(1000);
    if (LucyOffered.officeId(d) !== acct) {
      throw new Error('your ApplicantStream login couldn\'t open account ' + acct + ' (it showed ' +
                      (LucyOffered.officeId(d) || 'no calendar') + ')');
    }
    await wait(4000);                       // rows fill in after the page loads
    const got = await LucyOffered.read(d);
    LucyOffered.isCalendar(document);       // reader back on this tab
    return got;
  }
  async function switchBack(acct) {
    if (TOK) await frameLoad(BASE + '?p=104&rqst=' + TOK + '&newOfficeId=' + acct, 20000);
    const f = document.getElementById('lucy-oa-frame');
    if (f) f.remove();
  }

  function render(office, people, already, accounts, problems) {
    accounts = accounts || [LucyOffered.officeId()];
    problems = problems || [];
    const loc = '<div class="lucy-oa-loc">📍 ' + esc(office.city) + ', ' + esc(office.state) +
      ' <span class="lucy-oa-acct">· account' + (accounts.length > 1 ? 's ' : ' ') + esc(accounts.join(', ')) + '</span></div>' +
      problems.map(pr => '<div class="lucy-oa-err">⚠️ Account ' + esc(pr.acct) + ' wasn\'t read: ' + esc(pr.why) +
                         '. Nobody from it is on this list.</div>').join('');
    const mode = office.mode === 'live' ? '' :
      '<div class="lucy-oa-test">Test mode: checked, not sent.</div>';
    if (!people.length) {
      shell(mode + loc + '<p>Nobody marked <b>Yes</b> for Offer Position today yet.</p>');
      return;
    }
    // NEW people on top, ticked; anyone ALREADY SENT folded away underneath
    // (Megan 11/06: a list of "already sent" lines looked bad). They can still
    // be opened and ticked to send again -- the duplicate prompt still asks.
    const row = (p, i) => {
      const email = (p.email || '').trim();
      const done = email && already[email.toLowerCase()];
      const indeed = /@indeedemail\.com$/i.test(email);
      const note = !email ? 'no email in ApplicantStream'
        : done ? 'sent ' + done
        : indeed ? 'Indeed forwarding email — check it' : '';
      return '<label class="lucy-oa-row' + (email ? '' : ' off') + '"><input type="checkbox" data-i="' + i + '"' +
        (email && !done ? ' checked' : '') + (email ? '' : ' disabled') + '> ' +
        esc(p.first_name + ' ' + p.last_name) + (note ? ' <span class="lucy-oa-note">— ' + esc(note) + '</span>' : '') +
        '</label>';
    };
    const isDone = p => { const e = (p.email || '').trim().toLowerCase(); return !!(e && already[e]); };
    const list = (filter) => {
      let lastAcct = null, html = '';
      people.forEach((p, i) => {
        if (!filter(p)) return;
        if (accounts.length > 1 && p.acct !== lastAcct) {
          html += '<div class="lucy-oa-accthead">Account ' + esc(p.acct) + '</div>';
          lastAcct = p.acct;
        }
        html += row(p, i);
      });
      return html;
    };
    const fresh = people.filter(p => !isDone(p)).length;
    const old = people.length - fresh;
    const top = fresh
      ? '<p class="lucy-oa-pick">Tick who should get one (' + fresh + '):</p>' + list(p => !isDone(p))
      : '<div class="lucy-oa-ok">✅ Everyone offered today has already been sent one.</div>';
    const folded = old
      ? '<details class="lucy-oa-done"><summary>Already sent today (' + old + ') — open to send again</summary>' +
        list(isDone) + '</details>'
      : '';
    shell(mode + loc + top + folded +
      '<button id="lucy-oa-send" class="lucy-oa-primary"></button><div id="lucy-oa-result"></div>');
    const btn = panel.querySelector('#lucy-oa-send');
    const boxes = Array.from(panel.querySelectorAll('input[type=checkbox]'));
    const count = () => {
      const n = boxes.filter(b => b.checked).length;
      btn.textContent = '📨 Send background checks (' + n + ')';
      btn.disabled = !n;
    };
    boxes.forEach(b => b.addEventListener('change', count));
    count();
    const send = async (picked, resend) => {
      btn.disabled = true;
      btn.textContent = 'Sending to ' + owner() + ' Lucy ECO machine…';
      const out = await ask('send', {office: office.office, people: picked, resend: resend || '',
                                     appstream: Array.from(new Set(picked.map(p => p.acct))).join(', ')});
      if (out.needs_confirm) {           // already sent before: the admin decides
        confirmResend(picked, out.duplicates || []);
        count();
        return;
      }
      if (!out.ok) {
        result('err', esc(out.error || 'Didn\'t go through.'));
        count();
        return;
      }
      if (out.skipped_all) {
        result('ok', 'Nothing sent — everyone picked had already been sent one.');
        count();
        return;
      }
      const dupEmails = resend === 'skip' ? (panel._dups || []) : [];
      const sentNames = picked.filter(p => !dupEmails.includes((p.email || '').toLowerCase()))
                              .map(p => (p.first_name + ' ' + p.last_name).trim());
      if (live()) await chrome.storage.local.set({lastSend: {office: office.office, job_id: out.job_id,
                                                 at: new Date().toISOString(), names: sentNames,
                                                 test: office.mode !== 'live'}});
      // Everyone on today's list, and why each one left out was left out.
      const nm = p => (p.first_name + ' ' + p.last_name).trim();
      const pickedSet = new Set(picked);
      const notSent = [];
      people.forEach(p => {
        const email = (p.email || '').trim().toLowerCase();
        if (!email) notSent.push({name: nm(p), why: 'no email in ApplicantStream'});
        else if (!pickedSet.has(p)) notSent.push({name: nm(p), why: already[email] ? 'already sent ' + already[email] + ' — not ticked' : 'not ticked'});
        else if (dupEmails.includes(email)) notSent.push({name: nm(p), why: 'already sent ' + (already[email] || 'before') + ' — skipped'});
      });
      watch(office.office, out.job_id, {total: people.length, asked: sentNames, notSent: notSent,
                                        live: office.mode === 'live'});
    };

    // "Already sent" = ask, never a silent second invite (Megan 11/06: alert
    // the admin, let them resend or not).
    const confirmResend = (picked, dups) => {
      panel._dups = dups.map(d => (d.email || '').toLowerCase());
      const others = picked.length - dups.length;
      const list = dups.map(d => '<li><b>' + esc(d.name) + '</b> — sent ' + esc(d.sent_on) + '</li>').join('');
      result('warn', '⚠️ <b>Already sent a background check:</b><ul>' + list + '</ul>Send to them again?' +
        '<div class="lucy-oa-choices">' +
        '<button class="lucy-oa-again">Send again to them too</button>' +
        '<button class="lucy-oa-skip">' + (others ? 'Skip them, send the other ' + others : 'Don\'t send') + '</button>' +
        '</div>');
      panel.querySelector('.lucy-oa-again').onclick = () => send(picked, 'all');
      panel.querySelector('.lucy-oa-skip').onclick = () => {
        if (!others) { result('ok', 'Nothing sent.'); return; }
        send(picked, 'skip');
      };
    };

    // LAST CHECK before anything goes (Megan 11/06): whose Sterling, which
    // calendar. Nothing is sent until "Yes, send".
    btn.onclick = () => {
      const picked = boxes.filter(b => b.checked).map(b => people[+b.dataset.i]);
      const whose = owner().replace(/'s$/, '').replace(/^the ICD$/, 'this office');
      result('confirm',
        '<div class="lucy-oa-confirm-title">⚠️ CONFIRM</div>' +
        'Send <b>' + picked.length + '</b> background check link' + (picked.length === 1 ? '' : 's') +
        ' from <b>' + esc(whose.toUpperCase()) + '\'S STERLING</b>?' +
        '<div class="lucy-oa-confirm-acct">ApplicantStream account' + (accounts.length > 1 ? 's' : '') +
        ' <b>' + esc(Array.from(new Set(picked.map(p => p.acct))).join(', ')) +
        '</b> · ' + esc(office.city) + ', ' + esc(office.state) + '</div>' +
        (accounts.length > 1 ? 'Make sure these are the correct accounts.' : 'Make sure you\'re on the correct calendar.') +
        '<div class="lucy-oa-choices"><button class="lucy-oa-again lucy-oa-yes">Yes, send</button>' +
        '<button class="lucy-oa-skip lucy-oa-no">Cancel</button></div>');
      panel.querySelector('.lucy-oa-yes').onclick = () => send(picked, '');
      panel.querySelector('.lucy-oa-no').onclick = () => result('wait', 'Nothing sent.');
    };
  }

  function result(kind, html) {
    const el = panel && panel.querySelector('#lucy-oa-result');
    if (el) el.innerHTML = '<div class="lucy-oa-' + kind + '">' + html + '</div>';
  }

  // "Sent to 13/14" + every person who didn't get one and why (Megan 11/06).
  function summary(r, ctx) {
    const total = ctx.total || (ctx.asked || []).length;
    const done = r.status === 'sent' ? (r.sent || []) : r.status === 'dry_run' ? (r.would_send || []) : [];
    const notSent = (ctx.notSent || []).slice();
    const doneSet = new Set(done);
    const why = r.status === 'sent' || r.status === 'dry_run'
      ? 'Lucy couldn\'t use their name or email'
      : (r.error || 'didn\'t go through');
    (ctx.asked || []).forEach(n => {
      if (doneSet.has(n)) return;
      if ((r.unconfirmed || []).includes(n)) notSent.push({name: n, why: 'not sure it went out — check Sterling before sending again'});
      else notSent.push({name: n, why: why});
    });
    const head = r.status === 'dry_run'
      ? '🧪 Test run — would have sent to <b>' + done.length + '/' + total + '</b> (nothing sent)'
      : r.status === 'sent'
        ? (done.length === total ? '✅' : '⚠️') + ' Sent to <b>' + done.length + '/' + total + '</b>'
        : '⚠️ Sent to <b>0/' + total + '</b>';
    const list = done.length ? '<ol class="lucy-oa-names">' + done.map(n => '<li>' + esc(n) + '</li>').join('') + '</ol>' : '';
    const miss = notSent.length
      ? '<div class="lucy-oa-miss"><b>Not sent (' + notSent.length + '):</b><ul>' +
        notSent.map(m => '<li><b>' + esc(m.name) + '</b> — ' + esc(m.why) + '</li>').join('') + '</ul></div>'
      : '';
    return '<div class="lucy-oa-head2">' + head + '</div>' + list + miss;
  }

  // Whose computer does the sending: the calendar header's "Owner: Rafael
  // Hidalgo" (Megan 11/06: name the ICD, not "your office computer").
  function owner() {
    const m = (document.body.innerText || '').match(/Owner:\s*([A-Za-z.'\- ]+?)\s*(?:\n|ALPHALETE|$)/);
    const name = m ? m[1].trim() : '';
    return name ? name + '\'s' : 'the ICD\'s';
  }

  // The ICD's Lucy ECO machine asks every ~3 minutes. Show the steps and a
  // running clock so the admin can see it's moving (Megan 11/06).
  // Leaving is safe: the request already sits on the relay and the ECO
  // machine does it either way -- this panel only watches for the answer.
  function watch(officeKey, jobId, ctx) {
    ctx = ctx || {total: 0, asked: [], notSent: [], live: false};
    clearInterval(pollTimer);
    clearInterval(tickTimer);
    const who = owner(), Who = who.replace(/^the/, 'The');
    const started = Date.now();
    let stage = 1, late = false;           // 1 = waiting for pickup, 2 = working
    // ESTIMATE: pickup within 3 min (the machine's check), then ~4 min in
    // Sterling (Raf's live send 11/06 took 4 min end to end). Re-aimed at pickup.
    const PICKUP_MS = 3 * 60000, WORK_MS = 4 * 60000;
    let eta = started + PICKUP_MS + WORK_MS;
    const at = t => new Date(t).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
    const etaText = () => Date.now() < eta
      ? 'Should be done by about <b>' + at(eta) + '</b> (~' + Math.max(1, Math.ceil((eta - Date.now()) / 60000)) + ' min left)'
      : 'Taking a little longer than usual — still working…';
    const pct = () => Math.min(95, Math.round(100 * (Date.now() - started) / (eta - started)));
    const clock = ms => { const s = Math.floor(ms / 1000); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
    const step = (n, text, hint) => {
      const icon = n < stage ? '✅' : n === stage ? '<span class="lucy-oa-spin"></span>' : '⚪';
      return '<li class="' + (n < stage ? 'done' : n === stage ? 'now' : '') + '">' + icon + ' ' + text +
        (hint && n === stage ? ' <small>' + hint + '</small>' : '') + '</li>';
    };
    const draw = () => {
      result('wait',
        '<div class="lucy-oa-clock">⏱ ' + clock(Date.now() - started) + '</div>' +
        '<div class="lucy-oa-eta">' + etaText() + '</div>' +
        '<div class="lucy-oa-bar"><span style="width:' + pct() + '%"></span></div>' +
        '<ol class="lucy-oa-steps">' +
        '<li class="done">✅ Request sent</li>' +
        step(1, esc(Who) + ' Lucy ECO machine picks it up', '(it checks every 3 min)') +
        step(2, 'Signs in to Sterling and uploads the list', '(usually 3–5 min)') +
        step(3, 'Done', '') +
        '</ol>' +
        (late ? '<div class="lucy-oa-late">⚠️ Not picked up in 20 minutes — is ' + esc(who) + ' Lucy ECO machine on?</div>' : '') +
        '<div class="lucy-oa-stay">🚫 Please don\'t close this page or leave the calendar until it says <b>Done</b>.<br>You can use other tabs or browsers while you wait.</div>');
    };
    draw();
    // Only the clock ticks; a full redraw each second would restart the spinner.
    tickTimer = setInterval(() => {
      const el = panel && panel.querySelector('.lucy-oa-clock');
      if (el) el.textContent = '⏱ ' + clock(Date.now() - started);
      const e = panel && panel.querySelector('.lucy-oa-eta');
      if (e) e.innerHTML = etaText();
      const b = panel && panel.querySelector('.lucy-oa-bar span');
      if (b) b.style.width = pct() + '%';
    }, 1000);
    pollTimer = setInterval(async () => {
      const s = await ask('status', {office: officeKey, job_id: jobId});
      if (!s.ok) return;
      if (s.answered) {
        clearInterval(pollTimer);
        clearInterval(tickTimer);
        const r = s.result || {};
        const took = ' <small>(took ' + clock(Date.now() - started) + ')</small>';
        const sendBtn = panel && panel.querySelector('#lucy-oa-send');
        if (sendBtn) sendBtn.hidden = true;     // done: no second press by accident
        // Done: the tick list is history -- show only the result.
        if (panel) panel.querySelectorAll('.lucy-oa-row, .lucy-oa-pick, .lucy-oa-done, .lucy-oa-accthead').forEach(el => el.remove());
        result(r.status === 'sent' || r.status === 'dry_run' ? 'ok' : 'err', summary(r, ctx) + took);
      } else if (s.status === 'offered') {
        if (stage !== 2) { stage = 2; late = false; eta = Date.now() + WORK_MS; draw(); }
      } else if (!late && Date.now() - started > 20 * 60000) {
        late = true;
        draw();
      }
    }, 10000);
  }

  // The Lucy icon's "Send background checks" opens the same panel (popup.js).
  window.__lucyOfficeAdminOpen = open;
  button();
  new MutationObserver(button).observe(document.body, {childList: true, subtree: false});
  // The calendar fills in after the page loads: keep looking for a minute.
  let tries = 0;
  const again = setInterval(() => { button(); if (++tries > 30 || document.getElementById('lucy-oa-btn')) clearInterval(again); }, 2000);
})();
