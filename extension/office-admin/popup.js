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

function card(o, editing) {
  const ready = o.appstream && o.city && o.state;
  const badge = o.mode === 'live' ? '' : '<span class="test">test mode</span>';
  if (ready && !editing) {
    return '<div class="card" data-office="' + esc(o.office) + '"><h3>Office ' + esc(o.office) + badge + '</h3>' +
      '<div class="acct">ApplicantStream account: <b>' + esc(o.appstream) + '</b></div>' +
      '<div class="loc">📍 ' + esc(o.city) + ', ' + esc(o.state) + '</div>' +
      '<button class="link" data-edit="' + esc(o.office) + '">Change account number or location</button></div>';
  }
  const opts = '<option value="">Pick the state</option>' +
    STATES.map(s => '<option' + (s === o.state ? ' selected' : '') + '>' + s + '</option>').join('');
  return '<div class="card" data-office="' + esc(o.office) + '"><h3>Office ' + esc(o.office) + badge + '</h3>' +
    (ready ? '' : '<p class="muted">Set this office up once:</p>') +
    '<label>ApplicantStream account number</label><input data-f="appstream" inputmode="numeric" value="' + esc(o.appstream) + '" placeholder="e.g. 11280">' +
    '<label>State</label><select data-f="state">' + opts + '</select>' +
    '<label>City</label><input data-f="city" value="' + esc(o.city) + '">' +
    '<button data-save="' + esc(o.office) + '">Save</button></div>';
}

function home(me, editing) {
  show('signin', false); show('home', true);
  $('name').textContent = me.name;
  $('offices').innerHTML = (me.offices || []).map(o => card(o, editing === o.office)).join('');
  $('offices').querySelectorAll('[data-edit]').forEach(b => { b.onclick = () => home(me, b.dataset.edit); });
  $('offices').querySelectorAll('[data-save]').forEach(b => {
    b.onclick = async () => {
      err('');
      const c = b.closest('.card');
      const val = f => c.querySelector('[data-f="' + f + '"]').value.trim();
      const appstream = val('appstream').replace(/\D/g, '');
      if (!appstream) { err('Type the ApplicantStream account number (numbers only).'); return; }
      if (!val('state') || !val('city')) { err('Pick the state and type the city.'); return; }
      const out = await ask('set_office', {office: b.dataset.save, appstream, state: val('state'), city: val('city')});
      if (!out.ok) { err(out.error); return; }
      start();
    };
  });
  chrome.storage.local.get(['lastSend'], st => {
    const l = st.lastSend;
    $('last').textContent = l ? 'Last send (' + l.office + '): ' + new Date(l.at).toLocaleString() + ' — ' + l.names.join(', ') : '';
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
$('pass').addEventListener('keydown', e => { if (e.key === 'Enter') $('go').click(); });
$('out').onclick = () => chrome.runtime.sendMessage({type: 'signout'}, () => { show('home', false); show('signin', true); });
start();
