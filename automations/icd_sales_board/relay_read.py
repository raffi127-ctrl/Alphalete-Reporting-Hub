"""Per-rep daily sales for any ICD, off the Lucy ECO relay.

THIS IS HOW EVERY OTHER OFFICE GETS A BOARD. Raf's board is a Google Sheet we
can read; nobody else's is. What every office DOES have, once the ICD agent is
installed, is their own SaraPlus — read on their own laptop, because a SaraPlus
account sees exactly one owner and we are not collecting fifty passwords
(`automations/icd_alerts`). The laptop relays the numbers; this reads them back.

The agent already sends exactly what a board needs. `sara_read.read_day()`
returns `{'sales': {REP: {Int, Int Up, DTV, NL}}}` — the board's four columns,
per rep, for one day — and the relay lands it in column 9 of the 'ICD Relay'
tab as JSON, one row per office per day. So there is nothing to pull and
nothing to map: the shape on the wire IS the shape of the board.

WHAT THIS DELIBERATELY DOES NOT DO: decide who is on the roster, what team
they are on, or whether they are terminated. Those are the owner's to set and
live in `roster.py`. This returns what SaraPlus says each rep sold, and
nothing about who they are.

AN OFFICE WITH NO ROWS IS NOT AN OFFICE WITH NO SALES. It is an office whose
agent has not run — not installed, laptop asleep, no wifi. Callers get an
empty result and must say "no reading" rather than drawing a board of zeros;
see `last_reading()` for how stale the newest one is.
"""
from __future__ import annotations

import collections
import datetime as dt
import json

# The 'Lucy Access App' workbook the Apps Script relay writes into
# (resources/icd-alerts-relay.gs). One row per office per day, upserted, so a
# re-run replaces the day rather than appending a second reading.
RELAY_SHEET_ID = "1_5YGHhZ0gCYVZzHl7TPnP-6_75xaI0kcjPinQdVTlKg"
RELAY_TAB = "ICD Relay"

# Column headers, matched by NAME. The relay script appends columns as it
# grows — 'Last Posted Sales JSON' arrived after 'Sales JSON' — and an index
# would quietly read the wrong one the next time that happens.
COL_OFFICE = "Office"
COL_DAY = "Day"
COL_SALES = "Sales JSON"
COL_RECORDS = "Records JSON"
COL_LOCAL = "Local Time"
COL_AGENT = "Agent"

# The four the board keeps, in board order.
MEASURES = ["Int", "Int Up", "DTV", "NL"]


# ONE READ PER MINUTE, NOT PER QUESTION. Every public call here used to hit
# the API: rendering a board asked for the week, the status and then one more
# week per row of the week-over-week table, which was eight-plus full reads of
# the same tab to draw one page — slow enough that the board looked broken.
_CACHE: tuple = (0.0, [])
_TTL_SECONDS = 60


def _rows(force: bool = False) -> list:
    import time

    global _CACHE
    age = time.time() - _CACHE[0]
    if not force and _CACHE[1] and age < _TTL_SECONDS:
        return _CACHE[1]

    from automations.recruiting_report.fill import open_by_key

    ws = open_by_key(RELAY_SHEET_ID).worksheet(RELAY_TAB)
    grid = ws.get_all_values()
    if not grid:
        return []

    header = [str(h).strip() for h in grid[0]]
    rows = [dict(zip(header, r)) for r in grid[1:]
            if any(str(c).strip() for c in r)]
    _CACHE = (time.time(), rows)
    return rows


def _day(value):
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _loads(value) -> dict:
    """A blank cell, 'null' or malformed JSON all mean NOTHING RELAYED, which
    is not the same as an office with no sales. Never raises: one bad row must
    not take away every other office's board."""
    try:
        out = json.loads(str(value or "").strip() or "{}")
        return out if isinstance(out, dict) else {}
    except ValueError:
        return {}


def read_all() -> dict:
    """{office_key: {date: {REP: {Int, Int Up, DTV, NL}}}}.

    Rep names come back as SaraPlus writes them (upper case, office code
    already stripped by the agent). Matching them to a roster is the caller's
    problem, and deliberately so — see the module note."""
    out = collections.defaultdict(dict)
    for row in _rows():
        office = str(row.get(COL_OFFICE) or "").strip().lower()
        day = _day(row.get(COL_DAY))
        if not office or day is None:
            continue
        sales = _loads(row.get(COL_SALES))
        if not sales:
            continue
        out[office][day] = {
            str(name).strip(): _measures(vals)
            for name, vals in sales.items() if str(name).strip()
        }
    return dict(out)


def _measures(vals) -> dict:
    """Every number a feed sent for one rep, with the AT&T four defaulted.

    This used to keep ONLY Int / Int Up / DTV / NL, so a Box office's Sales,
    Volume, Big and Huge were dropped on the way in and its board read zero
    for every rep (Ryan, Carlos, 2026-09-22). The campaign decides which of
    these the board draws; the reader should not decide for it."""
    out = {m: 0 for m in MEASURES}
    for k, v in (vals or {}).items():
        try:
            out[str(k)] = int(float(v or 0))
        except (TypeError, ValueError):
            continue
    return out


def worked_names(office_key: str, start=None, end=None) -> set:
    """Reps who were WORKING but may have sold nothing.

    The relay carries a second list beside the sales: who ran a credit check.
    A credit check is a rep in front of a customer, so a name there with no
    sale is somebody who worked and blanked — which is exactly the row an
    owner opens a board to find. Without this they are simply absent, and an
    absent rep reads as a rep who was not there."""
    out = set()
    for row in _rows():
        if str(row.get(COL_OFFICE) or "").strip().lower() != (
                office_key or "").strip().lower():
            continue
        day = _day(row.get(COL_DAY))
        if day is None:
            continue
        if (start is not None and day < start) or (end is not None
                                                   and day > end):
            continue
        out.update(str(n).strip() for n in _loads(row.get(COL_RECORDS))
                   if str(n).strip())
    return out


def for_office(office_key: str, start=None, end=None) -> dict:
    """{date: {REP: metrics}} for one office, optionally bounded."""
    days = read_all().get((office_key or "").strip().lower(), {})
    return {d: reps for d, reps in sorted(days.items())
            if (start is None or d >= start) and (end is None or d <= end)}


def week(office_key: str, week_ending: dt.date) -> dict:
    """One Mon-Sun week: {REP: {day: metrics, 'total': metrics}}.

    Weeks END Sunday, the same boundary the sales board uses, so a relay week
    lines up with a board week rather than being off by one."""
    start = week_ending - dt.timedelta(days=6)
    by_rep: dict = collections.defaultdict(
        lambda: {"days": {}, "total": {m: 0 for m in MEASURES}})
    for day, reps in for_office(office_key, start, week_ending).items():
        for name, vals in reps.items():
            rec = by_rep[name]
            rec["days"][day] = vals
            for m, n in vals.items():          # every campaign's measures
                rec["total"][m] = rec["total"].get(m, 0) + n
    return dict(by_rep)


def last_reading(office_key: str) -> dict:
    """What we know about an office's agent, for saying WHY a board is empty.

    {'day': date|None, 'local_time': str, 'agent': str, 'reps': int,
     'sends_sales': bool}. `sends_sales` False with credit-check rows present
    means the agent is an old build that predates the sales passes — which is
    a different problem from a laptop that never ran, and the office is told
    to update rather than to check their wifi."""
    newest, newest_day = None, None
    recent_sales = False
    week_ago = dt.date.today() - dt.timedelta(days=7)
    for row in _rows():
        if str(row.get(COL_OFFICE) or "").strip().lower() != (
                office_key or "").strip().lower():
            continue
        day = _day(row.get(COL_DAY))
        if day is not None and (newest_day is None or day > newest_day):
            newest, newest_day = row, day
        # ANY sales in the last week proves the agent has the sales passes.
        # Judging it on the newest reading alone called every office broken
        # each morning, because at 10am nobody has sold yet (Aya, 2026-09-22:
        # sales every day Sep 17-21, an empty 11am reading today).
        if day is not None and day >= week_ago and _loads(row.get(COL_SALES)):
            recent_sales = True
    if newest is None:
        return {"day": None, "local_time": "", "agent": "", "reps": 0,
                "sends_sales": False}
    sales = _loads(newest.get(COL_SALES))
    return {
        "day": newest_day,
        "local_time": str(newest.get(COL_LOCAL) or "").strip(),
        "agent": str(newest.get(COL_AGENT) or "").strip(),
        "reps": len(sales),
        # False only when the office IS reporting (credit checks arrived) but
        # sent no sales — that is an old agent, not a quiet laptop.
        "sends_sales": bool(sales) or recent_sales,
        "has_records": bool(_loads(newest.get(COL_RECORDS))),
    }


def offices() -> list:
    """Every office key that has ever relayed sales, newest reading first."""
    seen = read_all()
    return sorted(seen, key=lambda k: max(seen[k]), reverse=True)
