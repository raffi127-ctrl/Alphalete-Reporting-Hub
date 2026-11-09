// The icon: sign in, ask Lucy for this week, see who is in it.
//
// Megan, 2026-11-08: "I don't want them to have to go to the hub." So the week
// is fetched here. The extension cannot read a sales board or a Blue Ink
// packet itself -- that is Python, on the office's own computer -- so it asks
// the relay for an `apex_week` job and waits for that computer to answer.
// Same relay, same sign-in and same shape as the background-check extension.
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const ask = (call, extra) => new Promise(r =>
    chrome.runtime.sendMessage({type: 'relay', call, extra}, r));

  let me = null, poll = null;

  function say(kind, html) {
    $('msg').className = kind;
    $('msg').innerHTML = html;
    $('msg').hidden = false;
  }

  // Monday of the current week — what "this week" means everywhere else here.
  function monday() {
    const d = new Date();
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') +
           '-' + String(d.getDate()).padStart(2, '0');
  }

  async function drawWeek() {
    const st = await chrome.storage.local.get(['week', 'loadedAt']);
    const w = st.week;
    const has = !!(w && w.data && w.data.length);
    $('have').hidden = !has;
    $('none').hidden = has;
    $('forget').hidden = !has;
    if (!has) return;
    $('wk').textContent = w.week || 'this week';
    const when = st.loadedAt ? new Date(st.loadedAt).toLocaleString([],
      {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : '';
    $('meta').textContent = w.data.length + ' new start' +
      (w.data.length === 1 ? '' : 's') + (when ? ' · fetched ' + when : '');
    // A TICK PER PERSON. The calendar says who showed up for training; the
    // admin says who actually goes into Apex (Megan, 2026-11-08: "admin should
    // be able to uncheck people she doesn't want to add"). Unticking is kept,
    // so Fill Apex only ever sees the ticked ones.
    const off = new Set(w.skip || []);
    $('names').innerHTML = w.data.map((p, i) =>
      '<div><label><input type="checkbox" data-i="' + i + '"' +
      (off.has(p.name) ? '' : ' checked') + '> ' + esc(p.name) + '</label></div>'
    ).join('');
    $('names').querySelectorAll('input[type=checkbox]').forEach(b => {
      b.onchange = async () => {
        const st2 = await chrome.storage.local.get(['week']);
        const wk = st2.week || {};
        const skip = new Set(wk.skip || []);
        const name = (wk.data || [])[+b.dataset.i].name;
        if (b.checked) skip.delete(name); else skip.add(name);
        wk.skip = [...skip];
        await chrome.storage.local.set({week: wk});
        countLine(wk);
      };
    });
    countLine(w);
  }

  // Say how many are actually going in, so an untick is visible.
  function countLine(w) {
    const off = new Set(w.skip || []);
    const going = (w.data || []).filter(p => !off.has(p.name)).length;
    const total = (w.data || []).length;
    $('meta').textContent = going + ' of ' + total + ' going into Apex' +
      (total - going ? ' · ' + (total - going) + ' unticked' : '');
  }

  async function draw() {
    const out = await ask('whoami');
    me = out && out.ok ? out : null;
    $('signin').hidden = !!me;
    $('home').hidden = !me;
    if (me) {
      $('name').textContent = me.name || me.username || '';
      await drawWeek();
    }
  }

  $('go').onclick = async () => {
    $('msg').hidden = true;
    const out = await ask('login', {username: $('user').value.trim(),
                                    password: $('pass').value});
    if (!out || !out.ok) { say('err', esc((out && out.error) || 'Could not sign in.')); return; }
    $('pass').value = '';
    };

  $('out').onclick = async () => {
    await new Promise(r => chrome.runtime.sendMessage({type: 'signout'}, r));
    draw();
  };

  $('forget').onclick = async () => {
    await chrome.storage.local.remove(['week', 'loadedAt']);
    $('msg').hidden = true;
    drawWeek();
  };

  // Ask the office's computer to build this week, then wait for its answer.
  // Leaving the popup is safe: the job sits on the relay either way, and this
  // only watches for the result.
  $('fetch').onclick = async () => {
    const office = (me && me.offices && me.offices[0]) ? me.offices[0].office : '';
    if (!office) { say('err', 'No office is set against your login.'); return; }
    $('fetch').disabled = true;
    say('wait', 'Asking Lucy for the week of <b>' + esc(monday()) + '</b>…');
    const out = await ask('apex_week', {office, week_start: monday()});
    if (!out || !out.ok) {
      say('err', esc((out && out.error) || "Lucy didn't take the request."));
      $('fetch').disabled = false;
      return;
    }
    if (out.already_running) {
      say('wait', 'That week is already being built — waiting for it.');
    }
    watch(office, out.job_id);
  };

  function watch(office, jobId) {
    const started = Date.now();
    clearInterval(poll);
    poll = setInterval(async () => {
      const mins = Math.round((Date.now() - started) / 60000);
      const s = await ask('status', {office, job_id: jobId});
      if (!s || !s.ok) return;
      if (!s.answered) {
        say('wait', 'Lucy is reading the training calendar and the signed ' +
                    'packets… <span class="muted">(' + mins + ' min)</span>' +
                    '<br><span class="muted">The office computer picks this up ' +
                    'every few minutes. You can close this.</span>');
        return;
      }
      clearInterval(poll);
      $('fetch').disabled = false;
      const r = s.result || {};
      if (r.status === 'error') { say('err', esc(r.error || 'It did not go through.')); return; }
      if (r.status === 'none') { say('ok', 'Nobody showed up for training that week.'); return; }
      const people = (r.added || []).map(n => ({name: n}));
      await chrome.storage.local.set({
        week: {week: r.week_start, data: people, build: '', built_at: Date.now(),
               notice: '', start: r.week_start},
        loadedAt: new Date().toISOString()
      });
      const held = (r.needs_hand || []).length;
      say('ok', 'Got ' + people.length + ' for ' + esc(r.week_start) +
                (held ? ' · ' + held + ' need a hand' : '') +
                '.<br>Now open Apex and press <b>Fill Apex</b>.');
      drawWeek();
    }, 10000);
  }

  // Two views behind one icon: the onboarding board (what the ICD lives in)
  // and the weekly Apex fill. The board opens first — it is the thing they
  // check all week, the fill is a Thursday job.
  function show(which) {
    const board = which === 'board';
    $('t-board').classList.toggle('on', board);
    $('t-apex').classList.toggle('on', !board);
    $('board').hidden = !board;
    for (const id of ['fetch', 'have', 'none', 'forget', 'msg', 'apexhint']) {
      const el = $(id);
      if (el) el.hidden = board || (id === 'forget' && el.dataset.empty === '1');
    }
    if (board) drawBoard();
    else drawWeek();
  }

  async function drawBoard() {
    const office = (me && me.offices && me.offices[0]) ? me.offices[0].office : '';
    if (!office) { $('board').innerHTML = '<p class="muted">No office is set against your login.</p>'; return; }
    $('board').innerHTML = '<p class="muted">Opening the board…</p>';
    const got = await window.LucyBoard.load(office, '');
    if (!got.ok) { $('board').innerHTML = '<p class="err">' + esc(got.error) + '</p>'; return; }
    window.LucyBoard.render($('board'));
  }

  $('t-board').onclick = () => show('board');
  $('t-apex').onclick = () => show('apex');

  draw().then(() => { if (me) show('board'); });
})();
