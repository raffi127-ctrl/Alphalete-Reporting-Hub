// Sign in, set the office's city + state once, see the last send.
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

$('state').innerHTML = '<option value="">Pick your state</option>' +
  STATES.map(s => '<option>' + s + '</option>').join('');

function home(me) {
  show('signin', false); show('home', true);
  $('name').textContent = me.name + ' · office ' + me.office;
  show('test', me.mode !== 'live');
  const has = me.city && me.state;
  $('loc').textContent = '📍 Office location: ' + me.city + ', ' + me.state;
  show('locview', has); show('locedit', !has);
  $('state').value = me.state || ''; $('city').value = me.city || '';
  chrome.storage.local.get(['lastSend'], st => {
    const l = st.lastSend;
    $('last').textContent = l ? 'Last send: ' + new Date(l.at).toLocaleString() + ' — ' + l.names.join(', ') : '';
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
$('chg').onclick = () => { show('locview', false); show('locedit', true); };
$('save').onclick = async () => {
  err('');
  if (!$('state').value || !$('city').value.trim()) { err('Pick the state and type the city.'); return; }
  const out = await ask('set_location', {state: $('state').value, city: $('city').value.trim()});
  if (!out.ok) { err(out.error); return; }
  start();
};
start();
