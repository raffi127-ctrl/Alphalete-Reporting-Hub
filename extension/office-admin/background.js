// Every relay call goes through here (the popup and the calendar page ask by
// message), so the sign-in token lives in ONE place: chrome.storage.local.
importScripts('config.js');

async function relay(call, extra) {
  const st = await chrome.storage.local.get(['token']);
  const body = {office_admin: Object.assign({call: call, token: st.token || ''}, extra || {})};
  let out;
  try {
    const res = await fetch(LUCY_RELAY_URL, {
      method: 'POST',
      // text/plain keeps it a "simple" request; Apps Script reads the body either way
      headers: {'Content-Type': 'text/plain;charset=utf-8'},
      body: JSON.stringify(body),
      redirect: 'follow'
    });
    const text = await res.text();
    try { out = JSON.parse(text); } catch (e) {
      out = {ok: false, error: "Lucy's relay answered a web page -- is the new relay version deployed?"};
    }
  } catch (e) {
    out = {ok: false, error: "Couldn't reach Lucy (" + e.message + ')'};
  }
  if (out.signed_out) await chrome.storage.local.remove(['token', 'me']);
  if (call === 'login' && out.ok && out.token) {
    await chrome.storage.local.set({token: out.token, me: out});
  }
  if (call === 'whoami' && out.ok) await chrome.storage.local.set({me: out});
  return out;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === 'relay') {
    relay(msg.call, msg.extra).then(reply);
    return true;   // async reply
  }
  if (msg && msg.type === 'signout') {
    chrome.storage.local.remove(['token', 'me', 'lastSend']).then(() => reply({ok: true}));
    return true;
  }
  return false;
});
