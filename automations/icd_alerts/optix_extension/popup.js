const $ = id => document.getElementById(id);
chrome.storage.local.get(["cfg", "last"], async ({cfg, last}) => {
  if (!cfg || !cfg.office) {      // the installer's pre-filled office + key
    try { const pre = await (await fetch(chrome.runtime.getURL("config.json"))).json();
          cfg = {office: pre.office || "", key: pre.key || "", dry: !!pre.dry}; } catch (e) { cfg = {}; }
  }
  $("office").value = cfg.office || ""; $("key").value = cfg.key || ""; $("dry").checked = !!cfg.dry;
  if (last) { $("last").textContent = `${last.at}: ${last.text}`; $("last").classList.toggle("bad", !last.ok); }
});
async function save() {
  const cur = (await chrome.storage.local.get("cfg")).cfg || {};
  await chrome.storage.local.set({cfg: {...cur, office: $("office").value.trim().toLowerCase(), key: $("key").value.trim(), dry: $("dry").checked}});
}
$("save").onclick = async () => { await save(); $("last").textContent = "Saved."; };
$("now").onclick = async () => {
  await save();       // what is on the screen is what runs -- no "Not set up yet" after typing it in
  $("last").textContent = "Reading Optix…";
  await chrome.runtime.sendMessage({readNow: true});
  const {last} = await chrome.storage.local.get("last");
  if (last) { $("last").textContent = `${last.at}: ${last.text}`; $("last").classList.toggle("bad", !last.ok); }
};
