// Lucy Optix — reads the Lead Details tab the office already has open in its
// OWN Chrome and sends per-rep COUNTS to the Lucy relay. Never an address.
// Megan 2026-11-06: Optix refuses data to any browser a program launches, so
// Lucy reads it from the office's everyday Chrome instead.
const RELAY = "https://script.google.com/macros/s/AKfycbwl4YR_SsJyWWRFV3cEQrNGq3vzqFDMUBGm4v692ZBJnfHVFMvnTfFm9vxG_r5cE4Wn/exec";
const LEAD_DETAILS = "optixtogo.verizon.com/SimplexMS/Web/LeadListWeb/";
const EVERY_MIN = 10;

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create("read", {periodInMinutes: EVERY_MIN}));
chrome.runtime.onStartup.addListener(() => chrome.alarms.create("read", {periodInMinutes: EVERY_MIN}));
chrome.alarms.onAlarm.addListener(a => { if (a.name === "read") readNow("timer"); });
chrome.runtime.onMessage.addListener((m, _s, reply) => {
  if (m && m.readNow) { readNow("button").then(reply); return true; }
});

function todayLocal(tz) {
  const p = new Intl.DateTimeFormat("en-US", {timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit"})
    .formatToParts(new Date()).reduce((o, x) => (o[x.type] = x.value, o), {});
  return {mdy: `${p.month}/${p.day}/${p.year}`, iso: `${p.year}-${p.month}-${p.day}`};
}
function hourLocal(tz) {
  return Number(new Intl.DateTimeFormat("en-US", {timeZone: tz, hour: "2-digit", hour12: false}).format(new Date()));
}

async function status(text, ok) {
  await chrome.storage.local.set({last: {text, ok, at: new Date().toLocaleTimeString()}});
}

// Runs IN THE PAGE (world MAIN) so it can see Optix's own Angular data.
// Sets the Disposition Date to today, presses Apply, waits for the result,
// and returns ONLY {agent, latestDisposition, totalDisposition} per row.
async function pageRead(mdy) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const boxes = [...document.querySelectorAll("input")].filter(i => /MM\/DD\/YYYY/i.test(i.placeholder || ""));
  if (boxes.length < 2) return {error: "Open Smart Leads → Lead Details in this tab (the date boxes were not found)."};
  for (const b of boxes.slice(0, 2)) {
    b.value = mdy;
    if (window.angular) { try { angular.element(b).val(mdy).triggerHandler("input"); angular.element(b).triggerHandler("change"); } catch (e) {} }
    b.dispatchEvent(new Event("input", {bubbles: true})); b.dispatchEvent(new Event("change", {bubbles: true}));
  }
  // textContent, not innerText: after an Apply the filter panel FOLDS AWAY and a
  // hidden button's innerText is "" (Megan's first real test, 2026-11-07).
  const apply = [...document.querySelectorAll("button")].find(b => /^\s*apply\s*$/i.test(b.textContent || ""));
  if (!apply) return {error: "No Apply button on this tab."};
  const before = document.body.innerText.match(/(\d+) dispositions from (\d+) unique leads/);
  apply.click();
  for (let i = 0; i < 60; i++) {           // up to ~60 s for Optix to answer
    await sleep(1000);
    const m = document.body.innerText.match(/(\d+) dispositions from (\d+) unique leads/);
    if (m && (!before || i > 3)) {
      const tr = [...document.querySelectorAll("tr")].find(t => t.querySelector("td"));
      let s = tr && window.angular ? angular.element(tr).scope() : null;
      while (s && !s.summaryList) s = s.$parent;
      if (!s) { if (m[1] === "0") return {rows: [], page: 0}; continue; }
      return {page: Number(m[1]), rows: s.summaryList.map(x => ({agent: x.agent,
        latestDisposition: x.latestDisposition, totalDisposition: x.totalDisposition}))};
    }
  }
  return {error: "Optix did not answer within a minute."};
}

function tally(rows, rules) {
  const keys = ["Doors", "Knocks", "Talk To", ...rules.rules.map(r => r[1]), "Other", "Do Not Knock"];
  const talk = new Set(["No Interest", "Declined", "Stop Back", "Appointment", "Sale Started", "Sale", "Canceled", "Existing Customer"]);
  const reps = {}, unknown = [];
  for (const r of rows) {
    const n = Math.floor(Number(r.totalDisposition || 0)), d = (r.latestDisposition || "").trim();
    if (n <= 0 && !d) continue;
    const rep = (r.agent || "").replace(/\s+/g, " ").trim() || "(unassigned)";
    const c = reps[rep] || (reps[rep] = Object.fromEntries([...new Set(keys)].map(k => [k, 0])));
    c.Doors += 1; c.Knocks += Math.max(n, 1);
    if (!d) continue;
    const hit = rules.rules.find(([rx]) => new RegExp(rx, "i").test(d));
    const b = hit ? hit[1] : "Other";
    c[b] += 1; if (talk.has(b)) c["Talk To"] += 1;
    if (new RegExp(rules.dnk, "i").test(d)) c["Do Not Knock"] += 1;
    if (b === "Other" && !unknown.includes(d)) unknown.push(d);
  }
  return {reps, unknown};
}

function boardRow(rep, c, cols) {
  const row = {Rep: rep, "Do Not Knock": c["Do Not Knock"] || 0, "First Knock": "", "Last Knock": "", "Gaps": "", "Total Gaps (min)": ""};
  for (const [b, col] of Object.entries(cols)) row[col] = (Number(row[col]) || 0) + (c[b] || 0);
  row["Inaccessible"] = Number(row["Inaccessible"]) - (c["Do Not Knock"] || 0);
  for (const k of Object.keys(row)) if (k !== "Rep") row[k] = String(row[k]);
  return row;
}

async function post(body) {
  const r = await fetch(RELAY, {method: "POST", body: JSON.stringify(body), redirect: "follow"});
  try { return await r.json(); } catch (e) { return {ok: r.ok}; }
}

async function readNow(why) {
  const cfg = (await chrome.storage.local.get("cfg")).cfg || {};
  // Test mode needs no key: it reads and counts, and sends nothing.
  if (!cfg.office || (!cfg.key && !cfg.dry)) return status("Not set up yet — click the Lucy icon and enter your office code (and key, unless Test mode).", false);
  const tz = cfg.tz || "America/Chicago";
  const h = hourLocal(tz);
  if (why === "timer" && (h < (cfg.start ?? 10) || h >= (cfg.end ?? 22))) return;
  const tabs = await chrome.tabs.query({url: "https://" + LEAD_DETAILS + "*"});
  if (!tabs.length) return status("Open Optix → Smart Leads → Lead Details and leave that tab open.", false);
  const rules = await (await fetch(chrome.runtime.getURL("rules.json"))).json();
  const day = todayLocal(tz);
  const [res] = await chrome.scripting.executeScript({target: {tabId: tabs[0].id}, world: "MAIN", func: pageRead, args: [day.mdy]});
  const out = res && res.result;
  if (!out || out.error) return status((out && out.error) || "Could not read the tab.", false);
  const {reps, unknown} = tally(out.rows, rules);
  const knocks = Object.values(reps).reduce((a, c) => a + c.Knocks, 0);
  if (out.page && knocks !== out.page) await status(`Optix says ${out.page} dispositions, counted ${knocks} — check before trusting.`, false);
  const rows = Object.keys(reps).sort().map(rep => boardRow(rep, reps[rep], rules.board_columns));
  const sales = Object.fromEntries(Object.entries(reps).filter(([, c]) => c.Sale).map(([rep, c]) => [rep, {Sales: c.Sale}]));
  if (cfg.dry) return status(`Test mode: ${rows.length} reps, ${knocks} knocks — nothing sent.`, true);
  const base = {office_key: cfg.office, key: cfg.key, day: day.iso, agent: "lucy-optix-ext/1.0.0", local_time: new Date().toISOString()};
  const a = await post({...base, knocks_rows: rows, knocks_time_tracker: []});
  if (Object.keys(sales).length) await post({...base, records: {}, sales});
  const note = unknown.length ? ` · new outcomes: ${unknown.join(", ")}` : "";
  return status(a && a.ok ? `Sent ${rows.length} reps, ${knocks} knocks${note}` : `Relay said: ${JSON.stringify(a)}`, !!(a && a.ok));
}
