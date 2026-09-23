"""Direct Deposit and Overrides per ICD — from the org tabs, for everyone.

Megan 2026-09-23: "you should have all Direct deposit amounts since we already
pull for everyone on the bulletin - we should pull their overrides as well."

WHY THIS MATTERS FOR THE P&L PAGE. That page reads an office's Focus Report
tab, and 27 of the board's 44 ICDs have no tab in any Focus Report we hold —
so their P&L is empty. These two numbers are not on the Focus Report at all:
they are already pulled ORG-WIDE every week for the DD and Override bulletins,
one row per ICD, whether or not that office keeps books. So every office gets
at least the money in, even the ones whose P&L we cannot see.

ONE WORKBOOK, TWO TABS ('Alphalete Org/Captainship Reports'):
  * `Org DDs Ongoing Report`       — 209 rows, col A the ICD, weekly columns
  * `Org Overrides Ongoing Report` —  75 rows, same shape

THE WEEK COLUMNS ARE FOUND BY THEIR HEADER, never by position: DD's weeks start
at column F and Overrides' at column E, and both tabs grow a column on the LEFT
every week, so an index would be wrong by one the following Monday.

THE FIRST ROW FOR A NAME WINS. The overrides tab lists its seven leaders twice
— once in ALL ORG and again as a section-2 total — and the section-1 row is the
person's own figure (see override_bulletin/compare.py, which exists largely to
keep that straight). Taking the first match takes section 1.

Read-only, and never raises: a missing tab means the page shows what it has.
"""
from __future__ import annotations

import datetime as dt
import re
import time

BOOK = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DD_TAB = "Org DDs Ongoing Report"
OVERRIDE_TAB = "Org Overrides Ongoing Report"

# 9.20.26 / 9.6.26 / 12.28.25 — the header spelling both tabs use.
_WEEK = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*$")

_CACHE: dict = {}
_TTL = 900


def _letters(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _week(text: str):
    m = _WEEK.match(text or "")
    if not m:
        return None
    mm, dd, yy = (int(g) for g in m.groups())
    try:
        return dt.date(yy + 2000 if yy < 100 else yy, mm, dd)
    except ValueError:
        return None


def _read(tab: str) -> dict:
    """{letters-only name: {date: cell}} for one tab, cached."""
    key = ("tab", tab)
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    out: dict = {}
    try:
        from automations.recruiting_report.fill import open_by_key, _retry
        grid = _retry(open_by_key(BOOK).worksheet(tab).get_all_values)
        head = grid[0] if grid else []
        cols = [(i, _week(head[i])) for i in range(len(head))
                if _week(head[i])]
        for row in grid[1:]:
            if not row:
                continue
            name = _letters(row[0])
            if not name or name in out:
                continue          # first row for a name wins — see the header
            out[name] = {d: (row[i] or "").strip()
                         for i, d in cols if i < len(row)}
    except Exception:   # noqa: BLE001 — the page says what it has
        out = {}
    _CACHE[key] = (now, out)
    return out


def _names_for(icd: str) -> list:
    names = [icd]
    try:
        from automations.focus_office_att import aliases as A
        names += [n for n in A.get_search_candidates(icd, A.load_aliases())
                  if n]
    except Exception:   # noqa: BLE001
        pass
    return [_letters(n) for n in names if _letters(n)]


def for_icd(icd: str) -> dict:
    """{'Direct Deposit': {date: value}, 'Override': {date: value}}.

    An empty dict for either means this ICD is not on that tab — which is a
    real answer and not a zero."""
    want = _names_for(icd)
    out = {}
    for label, tab in (("Direct Deposit", DD_TAB), ("Override", OVERRIDE_TAB)):
        rows = _read(tab)
        hit = next((rows[n] for n in want if n in rows), None)
        out[label] = {d: v for d, v in (hit or {}).items() if v}
    return out


def weeks_for(icd: str) -> list:
    """Every week either tab has a figure for this ICD, newest first."""
    got = for_icd(icd)
    return sorted({d for by in got.values() for d in by}, reverse=True)
