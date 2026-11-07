const $ = id => document.getElementById(id);
chrome.storage.local.get(["cfg", "last"], ({cfg = {}, last}) => {
  $("office").value = cfg.office || ""; $("key").value = cfg.key || ""; $("dry").checked = !!cfg.dry;
  if (last) { $("last").textContent = `${last.at}: ${last.text}`; $("last").classList.toggle("bad", !last.ok); }
});
$("save").onclick = async () => {
  const cur = (await chrome.storage.local.get("cfg")).cfg || {};
  await chrome.storage.local.set({cfg: {...cur, office: $("office").value.trim().toLowerCase(), key: $("key").value.trim(), dry: $("dry").checked}});
  $("last").textContent = "Saved.";
};
$("now").onclick = async () => {
  $("last").textContent = "Reading Optix…";
  await chrome.runtime.sendMessage({readNow: true});
  const {last} = await chrome.storage.local.get("last");
  if (last) { $("last").textContent = `${last.at}: ${last.text}`; $("last").classList.toggle("bad", !last.ok); }
};
