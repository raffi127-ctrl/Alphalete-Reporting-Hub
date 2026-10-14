"""Read every active rep's knock table off OwnerVille's Today's Activity.

WHERE IT COMES FROM (found 2026-10-14 in Raf's office, 11280):
  * Today's Activity, `index.cfm?p=88&rqst=…&tmPicker=MM/DD/YYYY` — the rep
    list. A rep who knocked that day has a two-number badge ("155 / 323"); one
    who did not has a single number ("591").
  * The same page with `&pane=today&pid=<rep id>` — that rep's day. The knock
    table (`#table-dashboard-store`: Location · Status · Time · Last Note · All
    Notes · GPS Verified?) is SERVER-RENDERED: every row is in the HTML, not
    just the 50 on screen, and each status pill carries its color inline
    (`style="background-color: #AE8446 !important"`).

So one plain GET per rep, parsed with DOMParser inside the logged-in page, is
the whole pull — ~1.7s a rep, no clicking, no rendering. (activityD2D.cfc's
getRepDispostionGeoData is the MAP's GeoJSON, 300 KB a rep — not this table.)
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.rep_knock_breakdown import config as C

_JS_REPS = r"""
async ({url}) => {
  const r = await fetch(url, {credentials: 'include'});
  const d = new DOMParser().parseFromString(await r.text(), 'text/html');
  const out = [];
  const seen = new Set();
  for (const a of d.querySelectorAll('a[href*="pane=today"]')) {
    let pid = '';
    try { pid = new URL(a.getAttribute('href'), location.href).searchParams.get('pid') || ''; }
    catch (e) {}
    if (!pid || seen.has(pid)) continue;
    seen.add(pid);
    const txt = a.textContent.replace(/\s+/g, ' ').trim();
    const m = txt.match(/^(.*?)\s+(\d+)\s*(?:\/\s*(\d+))?$/);
    if (!m) continue;
    out.push({pid: pid, name: m[1].trim(), badge: m[3] ? (m[2] + ' / ' + m[3]) : m[2],
              active: !!m[3]});
  }
  return {status: r.status, reps: out};
}
"""

_JS_REP_DAY = r"""
async ({url}) => {
  const r = await fetch(url, {credentials: 'include'});
  const html = await r.text();
  const d = new DOMParser().parseFromString(html, 'text/html');
  const table = d.querySelector('#table-dashboard-store');
  const rows = [];
  if (table) {
    for (const tr of table.querySelectorAll('tbody tr')) {
      const c = tr.cells;
      if (!c || c.length < 6) continue;
      const pill = c[1].querySelector('[style]');
      const style = pill ? (pill.getAttribute('style') || '') : '';
      const hex = (style.match(/#([0-9a-fA-F]{6})/) || [])[1] || '';
      const addr = c[0].innerHTML.split(/<br\s*\/?>/i)
        .map(s => s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim())
        .filter(Boolean).join(', ');
      rows.push({address: addr,
                 status: c[1].textContent.replace(/\s+/g, ' ').trim(),
                 color: hex,
                 time: c[2].textContent.trim(),
                 last_note: c[3].textContent.replace(/\s+/g, ' ').trim(),
                 gps: c[5].textContent.replace(/\s+/g, ' ').trim()});
    }
  }
  const body = d.body ? d.body.textContent.replace(/\s+/g, ' ') : '';
  const span = (body.match(/(\d+\s+hours?,\s*\d+\s+min)/) || [])[1] || '';
  return {status: r.status, found_table: !!table, rows: rows, time_knocking: span};
}
"""


def _list_url(rqst: str, day: dt.date) -> str:
    return ("https://v2.ownerville.com/index.cfm?p=%d&rqst=%s&tmPicker=%s"
            % (C.PAGE_TODAYS_ACTIVITY, rqst, day.strftime("%m/%d/%Y")))


def _rep_url(rqst: str, pid: str, day: dt.date) -> str:
    return _list_url(rqst, day) + "&pane=today&pid=%s" % pid


def pin_campaign(page, rqst: str) -> None:
    """TeleMapper pages show whatever campaign the session last had selected —
    by ANY job on this box. Load p=88 on RES AT&T so the fetches below inherit
    it (same guard gap_alerts._pin_campaign uses)."""
    page.goto("https://v2.ownerville.com/index.cfm?p=%d&rqst=%s&invD2DClientId=%s"
              % (C.PAGE_TODAYS_ACTIVITY, rqst, C.CAMPAIGN_ID),
              wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(800)


def active_reps(page, rqst: str, day: dt.date) -> List[Dict]:
    res = page.evaluate(_JS_REPS, {"url": _list_url(rqst, day)})
    if res.get("status") != 200:
        raise RuntimeError("Today's Activity list returned HTTP %s"
                           % res.get("status"))
    reps = res.get("reps") or []
    if not reps:
        raise RuntimeError("Today's Activity list had no reps at all — the "
                           "page shape changed or the session is not Raf's")
    return [r for r in reps if r.get("active")]


def rep_day(page, rqst: str, rep: Dict, day: dt.date) -> Dict:
    res = page.evaluate(_JS_REP_DAY, {"url": _rep_url(rqst, rep["pid"], day)})
    if res.get("status") != 200:
        raise RuntimeError("%s: HTTP %s" % (rep["name"], res.get("status")))
    if not res.get("found_table"):
        raise RuntimeError("%s: no knock table on the page (OwnerVille changed "
                           "#table-dashboard-store?)" % rep["name"])
    return {"pid": rep["pid"], "name": rep["name"], "rows": res["rows"],
            "time_knocking": res.get("time_knocking", "")}


def pull_day(page, rqst: str, day: dt.date, only: str = "") -> List[Dict]:
    """[{pid, name, rows, time_knocking}] for every rep who knocked on `day`.
    `only` = a name fragment, for a one-rep test."""
    reps = active_reps(page, rqst, day)
    if only:
        reps = [r for r in reps if only.lower() in r["name"].lower()]
    out = []
    for rep in reps:
        out.append(rep_day(page, rqst, rep, day))
    return out
