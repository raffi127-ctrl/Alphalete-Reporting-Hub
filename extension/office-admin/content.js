// On an ApplicantStream calendar: a "Send background checks" button. It reads
// today's Offer Position = Yes rows off THIS page (offered.js), marks who
// already got one, and sends the ticked people to the office's computer,
// which signs in to Sterling and bulk-uploads them (sterling_send.py).
(function () {
  'use strict';
  if (window.__lucyOfficeAdmin) return;
  window.__lucyOfficeAdmin = true;

  const ask = (call, extra) => new Promise(r => chrome.runtime.sendMessage({type: 'relay', call, extra}, r));
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let panel, pollTimer, tickTimer;

  function button() {
    if (document.getElementById('lucy-oa-btn') || !LucyOffered.isCalendar()) return;
    const b = document.createElement('button');
    b.id = 'lucy-oa-btn';
    b.textContent = '🛡️ Send background checks';
    b.addEventListener('click', open);
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
    // An office can have several accounts ("11280, 24153"), all on one Sterling.
    const accts = o => (String(o.appstream || '').match(/\d+/g) || []);
    const office = offices.find(o => pageOffice && accts(o).includes(pageOffice)) ||
      (!pageOffice && offices.length === 1 ? offices[0] : null);
    if (!office) {
      shell('<p class="lucy-oa-err">' + (pageOffice
        ? 'This calendar is ApplicantStream account ' + esc(pageOffice) + ', which isn\'t set on any of your offices. ' +
          'Check the account numbers in the Lucy Office Admin icon (top right of Chrome).'
        : 'Couldn\'t tell which office this calendar is. Open the calendar for one office.') + '</p>');
      return;
    }
    if (!office.city || !office.state) {
      shell('<p class="lucy-oa-err">Set office ' + esc(office.office) + '\'s city and state first: click the Lucy Office Admin icon at the top right of Chrome.</p>');
      return;
    }
    shell('<p>Reading today\'s second interviews…</p>');
    let people;
    try {
      people = await LucyOffered.read();
    } catch (e) {
      shell('<p class="lucy-oa-err">Couldn\'t read this calendar: ' + esc(e.message) + '</p>');
      return;
    }
    const already = (await ask('already', {office: office.office})).sent || {};
    render(office, people, already);
  }

  function render(office, people, already) {
    const loc = '<div class="lucy-oa-loc">📍 ' + esc(office.city) + ', ' + esc(office.state) +
      ' <span class="lucy-oa-acct">· account ' + esc(LucyOffered.officeId() || office.appstream) + '</span></div>';
    const mode = office.mode === 'live' ? '' :
      '<div class="lucy-oa-test">Test mode: checked, not sent.</div>';
    if (!people.length) {
      shell(mode + loc + '<p>Nobody marked <b>Yes</b> for Offer Position today yet.</p>');
      return;
    }
    const rows = people.map((p, i) => {
      const email = (p.email || '').trim();
      const done = email && already[email.toLowerCase()];
      const indeed = /@indeedemail\.com$/i.test(email);
      const note = !email ? 'no email in ApplicantStream'
        : done ? 'already sent ' + done
        : indeed ? 'Indeed forwarding email — check it' : '';
      return '<label class="lucy-oa-row' + (email ? '' : ' off') + '"><input type="checkbox" data-i="' + i + '"' +
        (email && !done ? ' checked' : '') + (email ? '' : ' disabled') + '> ' +
        esc(p.first_name + ' ' + p.last_name) + (note ? ' <span class="lucy-oa-note">— ' + esc(note) + '</span>' : '') +
        '</label>';
    }).join('');
    shell(mode + loc + '<p>Tick who should get one:</p>' + rows +
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
      const out = await ask('send', {office: office.office, people: picked, resend: resend || ''});
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
      await chrome.storage.local.set({lastSend: {office: office.office, job_id: out.job_id,
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

    btn.onclick = () => send(boxes.filter(b => b.checked).map(b => people[+b.dataset.i]), '');
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
