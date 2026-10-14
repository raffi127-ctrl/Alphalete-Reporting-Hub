"""Pull every knock for Raf's office from OwnerVille, one day at a time.

Source: OwnerVille V2 → TeleMapper Leads → Today's Activity (p=88), the
"Lead Knocks" table on a rep's page. Its data call is
    components/telemapper/activityD2D.cfc?method=getD2DKnocksReport
with startDate/endDate (MM/DD/YYYY) and an EMPTY repId, which returns every
knock in the signed-in office: time, address, disposition, OwnerVille's
colour, and the GPS check ("Success, 95 feet is within range of 799 feet." /
"Failure, 1.2 miles is out of range of 799 feet." / "Failure, User denied
Geolocation" / "GPS data not available"). includePing=0 keeps GPS pings out.

A finished day (pulled on a later date) is cached to output/; only today is
re-pulled each hour.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from automations.rep_knock_threads import config as C

_REP_RE = re.compile(r'rep-name-wrapper">\s*(.*?)\s*\((\d+)\)', re.S)
_FEET_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(feet|foot|miles?|mi)\b", re.I)

# Fetch inside the page (the session's cookies), and drop the heavy HTML
# fields before handing rows back to Python.
_FETCH_JS = """async ({rqst, mdy}) => {
  const p = new URLSearchParams({method: 'getD2DKnocksReport', rqst,
      startDate: mdy, endDate: mdy, officeId: '', repId: '', includePing: '0',
      draw: '1', start: '0', length: '-1'});
  const r = await fetch('/components/telemapper/activityD2D.cfc', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: p.toString()});
  const text = await r.text();
  if (r.status !== 200) return {status: r.status, rows: null, head: text.slice(0, 300)};
  let d;
  try { d = JSON.parse(text); } catch (e) { return {status: r.status, rows: null, head: text.slice(0, 300)}; }
  return {status: r.status, rows: (d.data || []).map(x => ({
      rep: x.rep, office: x.office, statusName: x.statusName,
      when: x.knockDateLocal, address: x.rawAddress, gps: x.gps,
      color: x.D2DColorHex, knockId: x.locknockid}))};
}"""


class PullError(RuntimeError):
    pass


def gps_kind(text: str) -> str:
    """'ok' | 'fail' | 'none' from OwnerVille's GPS sentence."""
    t = (text or "").strip().lower()
    if t.startswith("success"):
        return "ok"
    if t.startswith("failure"):
        return "fail"
    return "none"


def gps_reason(text: str) -> str:
    """Short plain-English reason for a failure, for the image + alert line."""
    t = (text or "").lower()
    if "out of range" in t:
        return "Too far from door"
    if "denied" in t:
        return "Location turned off"
    if "time" in t:
        return "GPS timed out"
    return "GPS failed"


def gps_short(text: str) -> str:
    """'95 ft' / '1.2 mi away' / 'Location off' — fits one table cell."""
    k = gps_kind(text)
    if k == "none":
        return "No GPS"
    m = _FEET_RE.search(text or "")
    if k == "ok":
        return f"{m.group(1)} ft" if m else "OK"
    if m and "out of range" in (text or "").lower():
        unit = "ft" if m.group(2).lower().startswith("f") else "mi"
        return f"{m.group(1)} {unit} away"
    return gps_reason(text)


def normalize(raw: dict) -> dict:
    m = _REP_RE.search(raw.get("rep") or "")
    if not m:
        raise PullError("a knock row has no rep name/id — OwnerVille changed "
                        "the Lead Knocks table")
    return {
        "rep": " ".join(m.group(1).split()),
        "rep_id": m.group(2),
        "office": raw.get("office") or "",
        "when": raw.get("when") or "",           # 'YYYY-MM-DD HH:MM:SS', rep-local
        "status": (raw.get("statusName") or "").strip(),
        "color": raw.get("color") or "#CCCCCC",
        "address": " ".join((raw.get("address") or "").split()),
        "gps": raw.get("gps") or "",
        "knock_id": raw.get("knockId"),
    }


def check_office(rows: list[dict], day: dt.date) -> None:
    """Every row must be Raf's office — the session is shared and moves."""
    bad = {r["office"] for r in rows if C.OFFICE_ID not in r["office"]}
    if bad:
        raise PullError(f"{day}: rows came back for {sorted(bad)}, not "
                        f"{C.OFFICE_LABEL} — the ownerville session is on another "
                        "office. Refusing to post someone else's reps.")


def _cache_path(day: dt.date):
    return C.CACHE_DIR / f"{day.isoformat()}.json"


def _read_cache(day: dt.date):
    p = _cache_path(day)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _write_cache(day: dt.date, rows: list[dict]) -> None:
    C.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(day).write_text(json.dumps(rows))


def _fetch_day(page, rqst: str, day: dt.date, log=print) -> list[dict]:
    mdy = day.strftime("%m/%d/%Y")
    last = None
    for attempt in range(3):
        res = page.evaluate(_FETCH_JS, {"rqst": rqst, "mdy": mdy})
        if res and res.get("rows") is not None:
            rows = [normalize(r) for r in res["rows"]]
            check_office(rows, day)
            log(f"[rep_knocks] {day}: {len(rows)} knocks, "
                f"{len({r['rep_id'] for r in rows})} reps")
            return rows
        last = res
        page.wait_for_timeout(3000)
    raise PullError(f"{day}: OwnerVille knock report failed 3x "
                    f"(status {last and last.get('status')}: "
                    f"{(last or {}).get('head', '')[:120]!r})")


def pull_days(days: list[dt.date], today: dt.date, *, headless: bool = False,
              log=print) -> dict:
    """{date: [knock, ...]} for every day asked. Days before `today` come from
    the cache when present; everything else is one ownerville session."""
    out, need = {}, []
    for d in days:
        cached = _read_cache(d) if d < today else None
        if cached is not None:
            out[d] = cached
        else:
            need.append(d)
    if not need:
        return out

    from automations.shared.ownerville_knocks import capture_rqst
    from automations.shared.tableau_patchright import (
        OWNERVILLE_V2_URL, ownerville_session)

    with ownerville_session(headless=headless, allow_form_login=True,
                            session_wait_s=600) as page:
        page.goto(OWNERVILLE_V2_URL + "?p=2", wait_until="domcontentloaded")
        rqst = capture_rqst(page)
        if not rqst:
            raise PullError("ownerville: no rqst token after sign-in")
        # Land on p=88 so relative component URLs + cookies match the page.
        page.goto(f"{OWNERVILLE_V2_URL}?p=88&rqst={rqst}&pane=today",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        for d in need:
            rows = _fetch_day(page, rqst, d, log=log)
            out[d] = rows
            if d < today:
                _write_cache(d, rows)
    return out
