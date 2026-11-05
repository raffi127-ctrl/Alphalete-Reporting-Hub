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
  let panel, pollTimer;

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
    const office = offices.find(o => o.appstream && o.appstream === pageOffice) ||
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
      ' <span class="lucy-oa-acct">· account ' + esc(office.appstream) + '</span></div>';
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
    btn.onclick = async () => {
      const picked = boxes.filter(b => b.checked).map(b => people[+b.dataset.i]);
      btn.disabled = true;
      btn.textContent = 'Sending to your office computer…';
      const out = await ask('send', {office: office.office, people: picked});
      if (!out.ok) {
        result('err', out.error || 'Didn\'t go through.');
        count();
        return;
      }
      await chrome.storage.local.set({lastSend: {office: office.office, job_id: out.job_id, at: new Date().toISOString(),
                                                 names: picked.map(p => p.first_name + ' ' + p.last_name)}});
      watch(office.office, out.job_id);
    };
  }

  function result(kind, html) {
    const el = panel && panel.querySelector('#lucy-oa-result');
    if (el) el.innerHTML = '<div class="lucy-oa-' + kind + '">' + html + '</div>';
  }

  // The office computer asks every ~3 minutes; show where it is.
  function watch(officeKey, jobId) {
    result('wait', '⏳ Waiting for your office computer… (it checks every few minutes)');
    clearInterval(pollTimer);
    const started = Date.now();
    pollTimer = setInterval(async () => {
      const s = await ask('status', {office: officeKey, job_id: jobId});
      if (!s.ok) return;
      if (s.answered) {
        clearInterval(pollTimer);
        const r = s.result || {};
        if (r.status === 'sent') result('ok', '✅ Sent: ' + esc((r.sent || []).join(', ')));
        else if (r.status === 'dry_run') result('ok', '✅ Test run — nothing sent. Would have sent: ' + esc((r.would_send || []).join(', ')));
        else result('err', '⚠️ ' + esc(r.error || 'Didn\'t go through.') +
          (r.unconfirmed ? '<br>Not sure these went out — check Sterling before sending again: ' + esc(r.unconfirmed.join(', ')) : '') +
          (r.failed ? '<br>Not sent — send by hand: ' + esc(r.failed.join(', ')) : ''));
      } else if (s.status === 'offered') {
        result('wait', '⏳ Your office computer is sending them now…');
      } else if (Date.now() - started > 20 * 60000) {
        result('err', '⚠️ Your office computer hasn\'t picked this up in 20 minutes — is it on?');
      }
    }, 10000);
  }

  button();
  new MutationObserver(button).observe(document.body, {childList: true, subtree: false});
})();
