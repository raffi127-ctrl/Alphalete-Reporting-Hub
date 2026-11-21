"""The hidden 'Campaign Log' tab — the campaign zone's data store.

Lives in the org Recruiting Dashboard workbook but is NOT one of
funnel_board/build.py's five owned tabs, so the hourly rebuild never wipes it:
the zone formulas re-render every hour, the data survives here.

Column map (fixed; build.py's formulas and goal_sync.gs read these ranges):
    A:B   manager map      A manager (picker spelling) | B campaign key
    D:H   layout           D "campaign|slot" | E campaign | F slot | G kind | H label
    J:N   values           J "manager|weekISO|slot" | K manager | L week ending
                           (ISO yyyy-mm-dd, the WK column's date) | M slot | N value
                           (display TEXT: "288", "6.4", "79%")
    P:R   goals            P "manager|slot" | Q manager | R goal value (text)

All writes are RAW — "79%" must stay a string, never become 0.79.
Values/goals are UPSERTS keyed on the key column: manual rows typed on the
dashboard (synced in by Apps Script) survive stamper runs because the stamper
simply never emits their keys.
"""
from __future__ import annotations

import os
import time

import requests

from automations.org_campaign_metrics import layout as L

TAB = "Campaign Log"
SSID = (os.environ.get("ORG_CAMPAIGN_SSID")
        or os.environ.get("FUNNEL_SSID")
        or "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA")
API = "https://sheets.googleapis.com/v4/spreadsheets/" + SSID


def _call(S, path, payload, method="post"):
    r = getattr(S, method)(API + path, json=payload)
    if r.status_code != 200:
        raise RuntimeError("%s %s -> %s\n%s"
                           % (method.upper(), path, r.status_code, r.text[:800]))
    return r.json()


# One read's wait, and the pauses between tries after a timeout. Five tries
# over ~8 minutes, where three 120s waits gave up in 6 with no pause at all.
READ_TIMEOUT_S = 60
TIMEOUT_BACKOFF_S = (15, 30, 60, 90)


def _get(S, url, params=None, tries=5):
    """GET with retries. Reads are safe to repeat; on 10/5 one Sheets
    ReadTimeout on the values read killed a --write rerun after all three
    Tableau pulls had finished (~17 min of work lost).

    429 is retried too, with waits long enough to outlast a per-minute quota
    (2026-11-20: a 429 on the first read crashed the stamper on Lucy 2).

    TIMEOUTS (2026-11-21). The stamper failed 5 of 8 mornings (11/14, 15, 17,
    20, 21), every time a ReadTimeout on the Campaign Log read, every time
    ~9:00, and every hand re-run later in the morning passed. Two things sit
    on that read: (1) the Tableau pulls just kept this session idle for 20+
    minutes, long enough for its pooled HTTPS connection to go dead quietly,
    and (2) the funnel board's hourly rebuild rewrites this same workbook at
    :05. The old loop retried at once, on the same pool, three times at 120s,
    so all three landed in the same bad minute. Now a timeout drops the pooled
    connections (S.close(); the session reconnects on the next call), waits
    longer each time, and tries five times, which outlasts a rebuild."""
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=READ_TIMEOUT_S)
            busy = r.status_code == 429 or r.status_code >= 500
            if not busy or i == tries - 1:
                return r
            time.sleep(20 * (i + 1) if r.status_code == 429 else 5 * (i + 1))
            continue
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError):
            if i == tries - 1:
                raise
            try:
                S.close()
            except Exception:                               # noqa: BLE001
                pass
        time.sleep(TIMEOUT_BACKOFF_S[min(i, len(TIMEOUT_BACKOFF_S) - 1)])


def _get_json(S, url, params=None):
    """A read that FAILS LOUDLY. Never hand back an error body as data.

    WHY (2026-11-20). `_read_block` used to do `.json().get("values", [])`, so a
    429 or 403 read as an EMPTY tab. upsert_values / upsert_goals then rewrite
    from row 2 with only the incoming rows, clobbering every stored week and
    Carlos's typed goals (seed_only can't protect a goal it was told isn't
    there). A failed read must stop the run before any write."""
    r = _get(S, url, params=params)
    if r.status_code != 200:
        raise RuntimeError("GET %s -> %s\n%s"
                           % (url.replace(API, "") or "/", r.status_code,
                              r.text[:800]))
    return r.json()


def ensure_tab(S, log=print):
    """Create the hidden tab if missing; return its sheetId."""
    meta = _get_json(S, API, params={"fields": "sheets.properties(title,sheetId)"})
    sid = {s["properties"]["title"]: s["properties"]["sheetId"]
           for s in meta["sheets"]}
    if TAB in sid:
        return sid[TAB]
    res = _call(S, ":batchUpdate", {"requests": [{"addSheet": {"properties": {
        "title": TAB, "hidden": True,
        "gridProperties": {"rowCount": 20000, "columnCount": 20}}}}]})
    log("created hidden tab %r" % TAB)
    return res["replies"][0]["addSheet"]["properties"]["sheetId"]


def write_layout(S, log=print):
    """Full rewrite of the manager map (A:B) and layout (D:H) sections."""
    ensure_tab(S, log)
    mp = [["Manager", "Campaign"]] + [[m, c] for m, c in L.MANAGER_CAMPAIGN.items()]
    lay = [["Key", "Campaign", "Slot", "Kind", "Label"]]
    for camp, rows in L.LAYOUTS.items():
        for i, (kind, label) in enumerate(rows):
            lay.append(["%s|%d" % (camp, i + 1), camp, i + 1, kind, label])
    # blank-pad so a shrunken layout leaves no stale tail behind
    mp += [["", ""]] * max(0, 60 - len(mp))
    lay += [["", "", "", "", ""]] * max(0, 400 - len(lay))
    _call(S, "/values:batchUpdate", {"valueInputOption": "RAW", "data": [
        {"range": "'%s'!A1" % TAB, "values": mp},
        {"range": "'%s'!D1" % TAB, "values": lay},
    ]})
    log("layout written: %d managers, %d layout rows"
        % (len(L.MANAGER_CAMPAIGN), sum(len(r) for r in L.LAYOUTS.values())))


def _read_block(S, rng, width):
    rows = _get_json(S, API + "/values/'%s'!%s" % (TAB, rng)).get("values", [])
    out = []
    for r in rows:
        r = list(r) + [""] * (width - len(r))
        out.append(r[:width])
    return out


def upsert_values(S, rows, dry_run=False, log=print):
    """rows: iterable of (manager, week_iso, slot, value). Merge-by-key rewrite."""
    ensure_tab(S, log)
    cur = _read_block(S, "J2:N20000", 5)
    idx = {}
    order = []
    for r in cur:
        if r[0]:
            if r[0] not in idx:
                order.append(r[0])
            idx[r[0]] = r
    changed = 0
    for mgr, week, slot, val in rows:
        val = "" if val is None else str(val)
        key = "%s|%s|%s" % (mgr, week, slot)
        row = [key, mgr, week, str(slot), val]
        if idx.get(key, [None] * 5)[4] != val:
            changed += 1
        if key not in idx:
            order.append(key)
        idx[key] = row
    log("values: %d existing, %d incoming, %d changed"
        % (len(cur), len(list(idx)) - len(cur) + changed, changed))
    if dry_run:
        return changed
    out = [idx[k] for k in order]
    out += [["", "", "", "", ""]] * 50          # clear a little tail
    _call(S, "/values:batchUpdate", {"valueInputOption": "RAW", "data": [
        {"range": "'%s'!J2" % TAB, "values": out}]})
    return changed


def upsert_goals(S, rows, dry_run=False, seed_only=False, log=print):
    """rows: iterable of (manager, slot, value). Merge-by-key rewrite of P:R.

    seed_only=True writes a goal only where none is stored yet — the stamper's
    mode for BOX/NDS, where Carlos's typed goals (synced in by the Goal Sync
    script) must never be stomped by a weekly re-seed.
    """
    ensure_tab(S, log)
    cur = _read_block(S, "P2:R20000", 3)
    idx, order = {}, []
    for r in cur:
        if r[0]:
            if r[0] not in idx:
                order.append(r[0])
            idx[r[0]] = r
    changed = 0
    for mgr, slot, val in rows:
        val = "" if val is None else str(val)
        key = "%s|%s" % (mgr, slot)
        if seed_only and idx.get(key, ["", "", ""])[2] != "":
            continue
        if idx.get(key, [None] * 3)[2] != val:
            changed += 1
        if key not in idx:
            order.append(key)
        idx[key] = [key, mgr, val]
    log("goals: %d existing, %d changed" % (len(cur), changed))
    if dry_run:
        return changed
    out = [idx[k] for k in order]
    out += [["", "", ""]] * 20
    _call(S, "/values:batchUpdate", {"valueInputOption": "RAW", "data": [
        {"range": "'%s'!P2" % TAB, "values": out}]})
    return changed


def existing_goal(S, manager, slot):
    """The stored goal text for manager|slot, or ''. One read; used sparingly."""
    for r in _read_block(S, "P2:R20000", 3):
        if r[0] == "%s|%s" % (manager, slot):
            return r[2]
    return ""
