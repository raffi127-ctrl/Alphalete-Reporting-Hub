"""The roster side: who exists, who's new, who's gone.

Source: 'Alphalete SALES BOARD 2025', one tab per week named
'Sales Board WE 8.9'. Each week tab holds the roster block — col B numbered
1..n, col C the rep name — bounded below by a 'TOTALS' row in col C. Bounding
matters: BELOW that row the same tab carries a leaders table, a notes block and
a new-starts list that also put names in col C, and reading them as reps
inflated the roster from 64 to 177 on the first pass.

WHERE 'TERMINATED' ACTUALLY LIVES
Not in 'Field Status'. That column only ever reads 1st Wk / 2nd Wk / 3rd Wk /
4th Wk / 5th wk+ / RT / Extra — checked across all seven week tabs from 6.28 to
8.9, zero 'Terminated' among them. The word DOES appear on the tab, but only
down in the roll-call legend at rows 195-199, which is not per-rep data.

The real signal is the 'Termination Date' column being filled. That is what
this module reads, and a date in ANY week's tab terminates the rep — once
they're gone they stop appearing on later boards entirely, so the last board
they were on is the one carrying their date.

WEEK 2 = A NEW REP
'Field Status' == '2nd Wk' on the newest board is the weekly "make a tab for
this person" signal. The name ALSO carries a '(Wk 2)' suffix, but that suffix
migrates ('(Wk 2)' -> '(Wk 3)' -> dropped) while the tab keeps whatever it was
born with, so the status column is the reliable one and the suffix is only a
fallback.

Every column here is found by its header text, never by index: the tabs drift
week to week (Field Status is col CG on 8.9, col BX on 6.28).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.reps_gross_paycheck import names

SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"
TAB_RE = re.compile(r"^Sales Board WE (\d{1,2})\.(\d{1,2})\s*$", re.I)

WEEK2 = "2nd wk"


@dataclass
class Rep:
    """One person, merged across every week tab they appear on."""
    raw: str                                    # newest spelling seen
    key: str
    status_by_week: Dict[dt.date, str] = field(default_factory=dict)
    termination: Optional[dt.date] = None
    termination_raw: str = ""
    start: Optional[dt.date] = None
    last_seen: Optional[dt.date] = None
    seen_on: List[str] = field(default_factory=list)

    @property
    def terminated(self) -> bool:
        return self.termination is not None

    def is_week2(self, sunday: dt.date) -> bool:
        return self.status_by_week.get(sunday, "").strip().lower() == WEEK2


def week_tabs(spreadsheet, year: int = 2026) -> List[tuple]:
    """[(week-ending Sunday, tab title)] for every 'Sales Board WE m.d' tab.

    The titles carry no year. Every one of these boards is from the current
    season, so `year` stamps them; a January tab sitting next to a December one
    would need the same month-rollback trick pnl._week_columns uses, and this
    raises rather than guessing if that day ever comes.
    """
    out = []
    for ws in spreadsheet.worksheets():
        m = TAB_RE.match(ws.title)
        if not m:
            continue
        month, day = int(m.group(1)), int(m.group(2))
        try:
            out.append((dt.date(year, month, day), ws.title))
        except ValueError:
            continue
    return sorted(out)


def _parse_date(s: str) -> Optional[dt.date]:
    s = str(s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find_col(row, label: str) -> Optional[int]:
    want = label.strip().lower()
    for j, c in enumerate(row):
        if str(c or "").replace("\n", " ").strip().lower() == want:
            return j
    return None


def load(spreadsheet, sundays: List[dt.date] = None,
         year: int = 2026) -> Dict[str, Rep]:
    """{join key: Rep} merged across the requested week tabs (default: all)."""
    from automations.recruiting_report.fill import _retry
    tabs = week_tabs(spreadsheet, year)
    if sundays is not None:
        wanted = set(sundays)
        tabs = [(d, t) for d, t in tabs if d in wanted]
    if not tabs:
        raise RuntimeError(
            "no 'Sales Board WE m.d' tabs found — check the sales board "
            "workbook ID and that the weekly tabs still use that name.")

    ranges = [f"'{t}'!A1:DZ140" for _d, t in tabs]
    res = _retry(spreadsheet.values_batch_get, ranges)

    reps: Dict[str, Rep] = {}
    for (sunday, title), vr in zip(tabs, res["valueRanges"]):
        grid = vr.get("values", [])
        if not grid:
            continue
        width = max(len(r) for r in grid)
        grid = [r + [""] * (width - len(r)) for r in grid]

        status_col = _find_col(grid[0], "field status")
        term_col = _find_col(grid[0], "termination date")
        start_col = _find_col(grid[0], "start date")
        hdr = next((i for i, r in enumerate(grid[:8])
                    if str(r[1]).strip() == "#"), None)
        totals = next((i for i, r in enumerate(grid)
                       if str(r[2]).strip().upper() == "TOTALS"), None)
        if hdr is None or totals is None:
            raise RuntimeError(
                f"'{title}': couldn't bound the roster block "
                f"(header '#' row={hdr}, TOTALS row={totals}). Without both "
                "ends the leaders table below reads as reps — refusing to "
                "guess.")

        for i in range(hdr + 1, totals):
            row = grid[i]
            raw = str(row[2]).strip()
            if not raw:
                continue
            k = names.key(raw)
            if not k:
                continue
            rep = reps.get(k)
            if rep is None:
                rep = reps[k] = Rep(raw=raw, key=k)
            if rep.last_seen is None or sunday >= rep.last_seen:
                rep.raw, rep.last_seen = raw, sunday
            rep.seen_on.append(title)
            if status_col is not None:
                rep.status_by_week[sunday] = str(row[status_col]).strip()
            if term_col is not None:
                d = _parse_date(row[term_col])
                if d and (rep.termination is None or d > rep.termination):
                    rep.termination, rep.termination_raw = d, str(row[term_col]).strip()
            if start_col is not None:
                d = _parse_date(row[start_col])
                if d and (rep.start is None or d < rep.start):
                    rep.start = d
    return reps
