// Sign in once; per office: ApplicantStream account number + city + state,
// entered once and changeable (Megan 2026-11-04: admins can run several
// offices, and need to enter/change the account number).
const STATES = ['Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware',
  'District of Columbia', 'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas',
  'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi',
  'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey', 'New Mexico', 'New York',
  'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island',
  'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington',
  'West Virginia', 'Wisconsin', 'Wyoming'];
const $ = id => document.getElementById(id);
const ask = (call, extra) => new Promise(r => chrome.runtime.sendMessage({type: 'relay', call, extra}, r));
const show = (id, on) => { $(id).hidden = !on; };
const err = text => { $('msg').textContent = text || ''; show('msg', !!text); };
const esc = s => String(s || '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

// Every ApplicantStream account this office's admins send from -- all of
// them go to the office's one Sterling (Megan 2026-11-06: Raf's accounts).
const accts = o => (String(o.appstream || '').match(/\d+/g) || []);
const acctBox = n => '<input data-f="appstream" inputmode="numeric" value="' + esc(n) + '" placeholder="e.g. 11280">';

function card(o, editing) {
  const ready = o.appstream && o.city && o.state;
  const badge = o.mode === 'live' ? '' : '<span class="test">test mode</span>';
  if (ready && !editing) {
    return '<div class="card" data-office="' + esc(o.office) + '"><h3>Office ' + esc(o.office) + badge + '</h3>' +
      '<div class="acct">ApplicantStream account' + (accts(o).length > 1 ? 's' : '') + ': <b>' + esc(accts(o).join(', ')) + '</b></div>' +
      '<div class="loc">📍 ' + esc(o.city) + ', ' + esc(o.state) + '</div>' +
      '<button class="link" data-edit="' + esc(o.office) + '">Change account number or location</button></div>';
  }
  const opts = '<option value="">Pick the state</option>' +
    STATES.map(s => '<option' + (s === o.state ? ' selected' : '') + '>' + s + '</option>').join('');
  return '<div class="card" data-office="' + esc(o.office) + '"><h3>Office ' + esc(o.office) + badge + '</h3>' +
    (ready ? '' : '<p class="muted">Set this office up once:</p>') +
    '<label>ApplicantStream account number</label>' +
    (accts(o).length ? accts(o) : ['']).map(n => acctBox(n)).join('') +
    '<button class="link" data-more="1">+ Add another account (same Sterling)</button>' +
    (o.approved ? '<p class="muted">Approved for this office: ' + esc(o.approved) + '</p>'
                : '<p class="muted">No accounts approved for this office yet — ask Megan.</p>') +
    '<label>State</label><select data-f="state">' + opts + '</select>' +
    '<label>City</label><input data-f="city" value="' + esc(o.city) + '">' +
    '<button data-save="' + esc(o.office) + '">Save</button></div>';
}

function home(me, editing) {
  show('signin', false); show('home', true);
  $('name').textContent = me.name;
  $('offices').innerHTML = (me.offices || []).map(o => card(o, editing === o.office)).join('');
  $('offices').querySelectorAll('[data-edit]').forEach(b => { b.onclick = () => home(me, b.dataset.edit); });
  $('offices').querySelectorAll('[data-more]').forEach(b => {
    b.onclick = () => b.insertAdjacentHTML('beforebegin', acctBox(''));
  });
  $('offices').querySelectorAll('[data-save]').forEach(b => {
    b.onclick = async () => {
      err('');
      const c = b.closest('.card');
      const val = f => c.querySelector('[data-f="' + f + '"]').value.trim();
      const appstream = Array.from(c.querySelectorAll('[data-f="appstream"]'))
        .map(i => i.value.replace(/\D/g, '')).filter(Boolean).join(', ');
      if (!appstream) { err('Type the ApplicantStream account number (numbers only).'); return; }
      if (!val('state') || !val('city')) { err('Pick the state and type the city.'); return; }
      const out = await ask('set_office', {office: b.dataset.save, appstream, state: val('state'), city: val('city')});
      if (!out.ok) { err(out.error); return; }
      start();
    };
  });
  chrome.storage.local.get(['lastSend'], st => {
    const l = st.lastSend;
    // A numbered list -- one name per line is easy to read (Megan 11/06).
    $('last').innerHTML = l
      ? '<b>Last send' + (l.test ? ' (test — nothing sent)' : '') + '</b> · office ' + esc(l.office) + ' · ' +
        esc(new Date(l.at).toLocaleString([], {month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit'})) +
        ' · ' + l.names.length + ' ' + (l.names.length === 1 ? 'person' : 'people') +
        '<ol class="names">' + l.names.map(n => '<li>' + esc(n) + '</li>').join('') + '</ol>'
      : '';
  });
}

async function start() {
  const me = await ask('whoami');
  if (me.ok) home(me); else { show('signin', true); show('home', false); }
}

$('go').onclick = async () => {
  err('');
  const out = await ask('login', {username: $('user').value.trim(), password: $('pass').value});
  $('pass').value = '';
  if (out.ok) home(out); else err(out.error);
};
// Opens the panel on the calendar tab -- works even on a tab that was open
// before the extension was loaded (the floating button only appears after a reload).
$('run').onclick = async () => {
  err('');
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab || !/^https:\/\/([^/]+\.)?applicantstream\.com\//.test(tab.url || '')) {
    err('Open the ApplicantStream calendar in this tab first.');
    return;
  }
  if (!chrome.scripting) {        // new files, old install: Chrome hasn't reloaded the extension yet
    err('Update needed: open chrome://extensions and click ↻ on Lucy Office Admin, then try again.');
    return;
  }
  try {
    await chrome.scripting.insertCSS({target: {tabId: tab.id}, files: ['content.css']});
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['offered.js', 'content.js']});
    const [r] = await chrome.scripting.executeScript({target: {tabId: tab.id},
      func: () => { if (!window.__lucyOfficeAdminOpen) return false; window.__lucyOfficeAdminOpen(); return true; }});
    if (!r || !r.result) { err('Reload the calendar page and try again.'); return; }
    window.close();
  } catch (e) {
    err('Couldn\'t open on this page: ' + e.message);
  }
};
chrome.storage.local.get(['hideButton'], st => { $('showbtn').checked = !st.hideButton; });
$('showbtn').onchange = () => chrome.storage.local.set({hideButton: !$('showbtn').checked});
$('pass').addEventListener('keydown', e => { if (e.key === 'Enter') $('go').click(); });
$('out').onclick = () => chrome.runtime.sendMessage({type: 'signout'}, () => { show('home', false); show('signin', true); });
start();
