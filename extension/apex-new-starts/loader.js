// The EXTENSION half: the button, and where the week's list lives.
//
// It holds the list in chrome.storage.local, which is the point of being an
// extension. The bookmarklet kept it in the page's localStorage, so a reload
// could lose it and every fix had to arrive as a fresh paste. Here the list
// survives reloads, new tabs and Chrome restarts, and the code arrives by
// `git pull` like everything else.
(function () {
  'use strict';
  if (window.__ansLoader) return;
  window.__ansLoader = true;

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  let engineReady = false;

  document.addEventListener('ans-engine-ready', e => {
    engineReady = !!(e && e.detail && e.detail.ok);
  });

  // Ask, in case the page half loaded before this one was listening. The two
  // halves are separate content scripts in separate worlds and Chrome does not
  // promise which is injected first, so an announcement alone would be missed
  // whenever the page half wins the race -- and the button would then insist
  // the engine had not loaded for as long as the tab stayed open.
  function askEngine(ms) {
    if (engineReady) return Promise.resolve(true);
    return new Promise(resolve => {
      const done = () => { clearTimeout(t); clearInterval(i); resolve(engineReady); };
      const t = setTimeout(done, ms || 600);
      const i = setInterval(() => { if (engineReady) done(); }, 40);
      document.dispatchEvent(new CustomEvent('ans-ping'));
    });
  }
  document.addEventListener('ans-failed', e => {
    say('err', esc((e && e.detail && e.detail.error) || 'The run did not start.'));
  });

  function button() {
    if (document.getElementById('lucy-ans-btn')) return;
    const b = document.createElement('button');
    b.id = 'lucy-ans-btn';
    b.textContent = 'Fill Apex';
    b.title = 'Fill this week’s new starts into Apex';
    b.addEventListener('click', start);
    document.body.appendChild(b);
  }

  function say(kind, html) {
    let box = document.getElementById('lucy-ans-msg');
    if (!box) {
      box = document.createElement('div');
      box.id = 'lucy-ans-msg';
      document.body.appendChild(box);
    }
    box.className = 'lucy-ans-' + kind;
    box.innerHTML = html + '<button class="lucy-ans-x" title="Close">✕</button>';
    box.querySelector('.lucy-ans-x').onclick = () => box.remove();
  }

  function run(week) {
    document.getElementById('lucy-ans-msg')?.remove();
    // Only the TICKED people. The admin unticks in the icon; if that did not
    // reach the run, the tick would be decoration and somebody she took off
    // the list would get a payroll record anyway.
    const skip = new Set(week.skip || []);
    const data = (week.data || []).filter(p => !skip.has(p.name));
    if (!data.length) {
      say('err', 'Everybody is unticked \u2014 nothing to fill. '
               + 'Tick somebody in the Lucy icon first.');
      return;
    }
    document.dispatchEvent(new CustomEvent('ans-run', {detail: {
      week: week.week, build: week.build, built_at: week.built_at,
      notice: week.notice, start: week.start, data: data
    }}));
  }

  // The clipboard is read only when the button is pressed -- a user gesture,
  // never in the background. Nothing is read from any other page.
  async function fromClipboard() {
    let text = '';
    try {
      text = await navigator.clipboard.readText();
    } catch (e) {
      return {ok: false, error: 'Chrome would not let the clipboard be read. ' +
              'Click once anywhere on this page, then press Fill Apex again.'};
    }
    return window.ApexSetup.parse(text);
  }

  async function start() {
    if (!(await askEngine())) {
      say('err', 'The run engine has not loaded on this tab yet — reload '
               + 'Apex and press Fill Apex again.');
      return;
    }
    const held = (await chrome.storage.local.get(['week'])).week;
    if (held && held.data && held.data.length) {
      run(held);
      return;
    }
    say('wait', 'Looking for this week’s list on the clipboard…');
    const got = await fromClipboard();
    if (!got.ok) { say('err', esc(got.error)); return; }
    await chrome.storage.local.set({week: got, loadedAt: new Date().toISOString()});
    run(got);
  }

  // The icon's "Load this week from the clipboard" and "Start the run".
  chrome.runtime.onMessage.addListener((msg, _s, reply) => {
    if (!msg) return false;
    if (msg.type === 'ans-start') { start().then(() => reply({ok: true})); return true; }
    if (msg.type === 'ans-load') {
      (async () => {
        const got = await fromClipboard();
        if (got.ok) await chrome.storage.local.set({week: got, loadedAt: new Date().toISOString()});
        reply(got);
      })();
      return true;
    }
    return false;
  });

  button();
  new MutationObserver(button).observe(document.body, {childList: true, subtree: false});
})();
