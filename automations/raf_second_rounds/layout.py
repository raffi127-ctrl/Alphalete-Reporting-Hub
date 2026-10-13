"""Raf's 2nd-round tab as ONE table with a Month picker (Raf, Slack 2026-10-13).

    "make it so it pulls the names from the sales board for all the leaders.
     The recruiter will still manually enter the job offered and accepted.
     Can we add a dropdown that lets us pick the month so that we don't have to
     copy and paste to create a new month?"

THE SHAPE. The old '2nd rds %'s' tab puts every month side by side (October in
A-J, September in N-W, ...) and each new month is a hand copy-paste -- which is
how October arrived with no color rules and NS % dividing the wrong columns
(2026-10-13, sheet_format_audit). Here every month lives in ONE table, one row
per leader per month, newest month on top:

    Month | Team Name | Leader Name | 2nd rds conducted | Job offered | ...

and a slicer on the Month column is the dropdown. Picking a month hides the
other months' rows; the recruiter types into the rows they see, same as today.
The TOTALS row uses SUBTOTAL(109, ...), which skips rows the slicer hid, so it
always totals the month on screen. Color rules cover the whole % columns once,
so a new month can never come without them.

WHO GOES IN A NEW MONTH: every non-terminated leader on the sales board
(Level 1 / 2 / 3 / Mastermind -- gap_alerts.leaders, which already knows the
three ways the board marks a termination), PLUS anyone from last month who is
not on the board but had numbers (Aimee Garibay, Amjad Malhas... do 2nd rounds
without a sales-board row). Mid-month promotions are added to the current month
on the next run. Nobody is ever removed: a row may hold someone's typed numbers.

Pure functions only; run.py does the reading/writing. Python 3.9-safe.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from automations.gap_alerts.leaders import _fold

TAB = "2nd rds %'s - TEST"

# Column titles, left to right. Found by TITLE when reading the tab back;
# this order is only used when the tab is first built.
MONTH, TEAM, LEADER = "Month", "Team Name", "Leader Name"
CONDUCTED, OFFERED, OFFERED_PCT = "2nd rds conducted", "Job offered", "Job Offered %"
ACCEPTED, BOB_PCT = "BOB # / Accepted", "BOB %"
NS_SCHED, NS_SHOWED, NS_PCT = "New Start Scheduled", "New starts showed", "NS Showed %"
HEADERS = [MONTH, TEAM, LEADER, CONDUCTED, OFFERED, OFFERED_PCT,
           ACCEPTED, BOB_PCT, NS_SCHED, NS_SHOWED, NS_PCT]
COUNTS = [CONDUCTED, OFFERED, ACCEPTED, NS_SCHED, NS_SHOWED]
# % column -> (numerator, denominator, green at/above, red below). Cuts are the
# tab's own "Metric Goals" legend, same as sheet_format_audit.METRICS.
PCTS = {
    OFFERED_PCT: (OFFERED, CONDUCTED, 0.75, 0.65),
    BOB_PCT: (ACCEPTED, OFFERED, 0.70, 0.50),
    NS_PCT: (NS_SHOWED, NS_SCHED, 0.65, 0.50),
}

# Leaders, for this tab. gap_alerts tags only Level 1 / 2 / Mastermind; the
# board also has a 'Level 3' (Se7en Sins, WE 10.18) and they run 2nd rounds too.
LEVELS = ("level 1", "level 2", "level 3", "mastermind")


def month_label(day: dt.date) -> str:
    return day.strftime("%B %Y")          # 'October 2026'


def col_letter(c: int) -> str:
    """1 -> 'A'."""
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def clean_name(raw: str) -> str:
    """'Noemi (Ivette) Ontiveros' -> 'Noemi Ontiveros', 'Bill Hirwa (NC)' ->
    'Bill Hirwa'. The tab has always been typed without the board's tags and
    nicknames, so that is what a new row shows."""
    s = re.sub(r"\([^)]*\)", " ", str(raw or "").replace("\xa0", " "))
    return " ".join(s.split())


def _words(name: str) -> frozenset:
    s = _fold(clean_name(name)).lower()
    return frozenset(w for w in re.sub(r"[^a-z ]", " ", s).split()
                     if w not in {"jr", "sr", "ii", "iii"})


def same_person(a: str, b: str) -> bool:
    """One name's words all inside the other's: 'Justin Avila' = 'Justin
    Carlos Avila', 'Andrew Sanborn' = 'Andrew Sanborn Roadtrip'. Needs two
    words on the short side so a bare first name never matches."""
    wa, wb = _words(a), _words(b)
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return len(short) >= 2 and short <= long_


@dataclass(frozen=True)
class Person:
    name: str
    team: str = ""


@dataclass
class Row:
    """One leader-month row as read back from the tab (1-based sheet row)."""
    row: int
    month: str
    team: str
    name: str
    counts: Dict[str, str]

    def has_numbers(self) -> bool:
        return any(str(v).strip() not in ("", "0") for v in self.counts.values())


def new_month_people(leaders: Sequence[Person], last_month: Sequence[Row]) -> List[Person]:
    """Who a brand-new month starts with: the board's leaders, plus last
    month's off-board people who had numbers. Alphabetical, like the tab."""
    out = list(leaders)
    for r in last_month:
        if r.has_numbers() and not any(same_person(r.name, p.name) for p in out):
            out.append(Person(r.name, r.team))
    return sorted(out, key=lambda p: clean_name(p.name).lower())


def missing_from_month(leaders: Sequence[Person], month_rows: Sequence[Row]) -> List[Person]:
    """Leaders on the board with no row in this month yet (promoted mid-month,
    or the board was read before they were ranked)."""
    return [p for p in leaders
            if not any(same_person(p.name, r.name) for r in month_rows)]


def row_values(month: str, p: Person, row: int,
               counts: Optional[Dict[str, object]] = None) -> List[object]:
    """One full row: typed cells blank (or seeded), % cells as formulas."""
    col = {h: i + 1 for i, h in enumerate(HEADERS)}
    counts = counts or {}
    out = []  # type: List[object]
    for h in HEADERS:
        if h == MONTH:
            out.append(month)
        elif h == TEAM:
            out.append(p.team)
        elif h == LEADER:
            out.append(clean_name(p.name))
        elif h in PCTS:
            num, den = PCTS[h][0], PCTS[h][1]
            out.append("=iferror(%s%d/%s%d,0)" % (col_letter(col[num]), row,
                                                 col_letter(col[den]), row))
        else:
            out.append(counts.get(h, ""))
    return out


def months_in(rows: Sequence[Row]) -> List[str]:
    """Distinct months, in the order they sit on the tab (newest first)."""
    seen = []  # type: List[str]
    for r in rows:
        if r.month and r.month not in seen:
            seen.append(r.month)
    return seen


def month_block(rows: Sequence[Row], month: str) -> Tuple[List[Row], Optional[int]]:
    """(this month's rows, the sheet row just after its last one)."""
    mine = [r for r in rows if r.month == month]
    return mine, (max(r.row for r in mine) + 1 if mine else None)
