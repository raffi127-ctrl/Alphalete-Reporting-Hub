// The icon: which week is loaded, who is in it, and how to replace it.
// Everything that touches the page happens on the Apex tab; this is only the
// list the extension is holding.
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  function show(kind, text) {
    $('msg').className = kind;
    $('msg').textContent = text;
    $('msg').hidden = false;
  }

  async function draw() {
    const st = await chrome.storage.local.get(['week', 'loadedAt']);
    const w = st.week;
    const has = !!(w && w.data && w.data.length);
    $('have').hidden = !has;
    $('none').hidden = has;
    $('forget').hidden = !has;
    if (!has) return;
    $('wk').textContent = w.week || 'this week';
    const when = st.loadedAt ? new Date(st.loadedAt).toLocaleString([], {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : '';
    $('meta').textContent = w.data.length + ' new start' + (w.data.length === 1 ? '' : 's') +
      (when ? ' · loaded ' + when : '') + (w.build ? ' · board read ' + w.build : '');
    $('names').innerHTML = w.data
      .map(p => '<div>' + esc(p.name) + (p.start ? ' <span class="muted">' + esc(p.start) + '</span>' : '') + '</div>')
      .join('');
  }

  // The clipboard is read by the Apex tab, which is where the user gesture
  // and the page permission are. An Apex tab has to be open for that.
  async function ask(type) {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab || !/^https:\/\/apex\.herbjoyent\.com\//.test(tab.url || '')) {
      show('err', 'Open your Apex tab first, then press this again.');
      return null;
    }
    try {
      return await chrome.tabs.sendMessage(tab.id, {type});
    } catch (e) {
      show('err', 'Reload the Apex tab and try again.');
      return null;
    }
  }

  $('load').onclick = async () => {
    $('msg').hidden = true;
    const out = await ask('ans-load');
    if (!out) return;
    if (!out.ok) { show('err', out.error); return; }
    show('ok', 'Loaded ' + out.data.length + ' for ' + (out.week || 'this week') + '.');
    draw();
  };

  $('forget').onclick = async () => {
    await chrome.storage.local.remove(['week', 'loadedAt']);
    $('msg').hidden = true;
    draw();
  };

  draw();
})();
