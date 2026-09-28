"""Sales AND most of the knocking block — both off the weekly sales boards.

The knocking rows were the one part of this report expected to need live
OwnerVille pulls (~12 round-trips per office per week). They do not: Raf's
sales board already carries per-rep knock measures alongside the products.

`Sales Board WE 9.27` measures, read 2026-09-28:

    APPS · INT · INT UP · DTV · NL · TK · Cx
    AVG Total Knocks per day · Total Talk-To's · AVG TT's per day
    % of TT's per knock · AVG TTs per app

There are 17 `Sales Board WE m.d` tabs, back past WE 7.12, so a nine-week
backfill is nine reads — not ~800 OwnerVille round-trips.

WHAT MAPS CLEANLY, and what does not:

  The week totals answer the Mon-Fri knock rows only if the board's week IS
  Mon-Fri. It is not — the board runs Mon-Sat, and the 1on1 box asks for
  Monday-Friday and Saturday SEPARATELY ('Saturday Avg Doors / Day',
  'Saturday First knock'). So a week total cannot fill a Mon-Fri row without
  quietly folding Saturday into it.

  The board carries per-DAY blocks, which is where that split has to come
  from. Rows this module will not source are left for OwnerVille or left
  blank and reported — never approximated from a total that includes the day
  the row excludes. [[feedback_fill_but_flag]]

FIRST AND LAST KNOCK TIMES are not on the board in any form, so those four
rows (Mon-Fri first/last, Saturday first/last) stay unsourced here.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.local_office_1on1s import people as PEO

WEEK_TAB = re.compile(r"^Sales Board WE\s+(\d{1,2})\.(\d{1,2})$", re.I)

# 1on1 row label -> the board measure(s) that carry it, newest spelling first.
#
# THE BOARD RENAMES ITS OWN COLUMNS. 'Sales Board WE 8.2' and 'WE 8.16' head the
# apps column 'Total Apps'; from 'WE 8.30' it is 'APPS'. Looking for one
# spelling left Total Apps blank for three weeks while every other product on
# the same rows filled — a gap that reads as "sold nothing" rather than "looked
# under the wrong name". Each row therefore accepts every spelling the tabs in
# range actually use. [[feedback_no_hardcoded_columns]]
SALES = {
    "New INT":        ["INT"],
    "Upgrades":       ["INT UP"],
    "DTV's":          ["DTV"],
    "Wireless Lines": ["NL"],
    "Total Apps":     ["APPS", "Total Apps"],
}

# Nothing here: every knock row either needs the per-day split (see day_cells)
# or is not on the board at all. 'Monday - Saturday Total Apps' looks like a
# week total but is computed in day_cells so it comes from the same per-day
# numbers as everything beside it.
KNOCKS_WEEK: Dict[str, str] = {}

# The board carries SEVEN per-day blocks (Mon-Sun), each with
# Apps / Int / Int Up / DTV / NL / TK / Total Talk-To's / % of TT's per knock /
# AVG app per TT / Cx. That is where the Mon-Fri vs Saturday split comes from.
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
SATURDAY = "Saturday"

# Not on the board in any form — these four are TIMES, and the board records
# counts only. They stay unsourced until somebody wants an OwnerVille pull.
NOT_ON_BOARD = [
    "Mon - Friday AVG First Knock",
    "Mon - Friday AVG Last Knock",
    "Saturday First knock",
    "Saturday Last Knock",
]


def _num(v) -> Optional[float]:
    s = str(v or "").strip().replace(",", "").replace("%", "")
    if not s or s in {"-", "\u2014"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(v: Optional[float], *, pct=False, dp=1) -> Optional[str]:
    if v is None:
        return None
    if pct:
        return f"{v:.1f}%"
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:.{dp}f}"


def day_cells(days: Dict[str, Dict[str, str]], tab: str):
    """The knock rows, computed from one person's per-day numbers.

    AVERAGES DIVIDE BY DAYS ACTUALLY WORKED, not by 5. A rep who knocked three
    days did not average their week over five — that would report someone who
    worked hard on three days as a poor performer. A rep with no day at all
    gets nothing, not a zero.
    """
    def total(day_names, measure):
        vals = [_num(days.get(d, {}).get(measure)) for d in day_names]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    def worked(day_names):
        return sum(1 for d in day_names
                   if (_num(days.get(d, {}).get("TK")) or 0) > 0)

    out = []
    mf_tk, mf_tt = total(WEEKDAYS, "TK"), total(WEEKDAYS, "Total Talk-To's")
    mf_days = worked(WEEKDAYS)
    ms_apps = (total(WEEKDAYS + [SATURDAY], "Apps")
               or total(WEEKDAYS + [SATURDAY], "APPS"))
    sat_tk = total([SATURDAY], "TK")
    sat_tt = total([SATURDAY], "Total Talk-To's")

    def add(label, value, how):
        if value is not None:
            out.append((label, value, f"{tab!r} {how}"))

    add("Monday - Friday Total Knocks", _fmt(mf_tk), "sum TK Mon-Fri")
    add("Monday - Friday Total Talk Too's", _fmt(mf_tt), "sum Talk-To's Mon-Fri")
    add("Monday - Saturday Total Apps", _fmt(ms_apps), "sum Apps Mon-Sat")
    # A MISSING NUMERATOR IS NOT ZERO. The older board tabs carry per-day Apps
    # but no per-day TK or Talk-To's, and `mf_tt or 0` turned that absence into
    # '0.0%' — Anthony Marchetti's WE 9/6 read 286 knocks at a 0.0% talk-to
    # rate, which states he knocked 286 doors and spoke to nobody. Blank says
    # "the board did not record this"; 0% says something false and specific.
    # [[feedback_dont_explain_away_a_zero]]
    if mf_days and mf_tk is not None:
        add("Monday - Friday AVG Doors knocked / Day",
            _fmt(mf_tk / mf_days), f"sum TK Mon-Fri / {mf_days} days worked")
    if mf_days and mf_tt is not None:
        add("Mon - Friday avg Talk To's Day",
            _fmt(mf_tt / mf_days), f"sum Talk-To's Mon-Fri / {mf_days} days worked")
    if mf_tk and mf_tt is not None:
        add("Monday % Talk To's Per knocks",
            _fmt(100 * mf_tt / mf_tk, pct=True), "Talk-To's / TK, Mon-Fri")
    if ms_apps and (mf_tt is not None or sat_tt is not None):
        add("AVG Talk Too's per App",
            _fmt(((mf_tt or 0) + (sat_tt or 0)) / ms_apps), "Talk-To's / Apps, Mon-Sat")
    add("Saturday Avg Doors / Day", _fmt(sat_tk), "Saturday TK")
    add("Saturday avg Talk To's Day", _fmt(sat_tt), "Saturday Talk-To's")
    return out


def read_days(grid: List[List[str]], tab: str) -> Dict[str, Dict[str, Dict[str, str]]]:
    """{person key: {day: {measure: value}}} off the board's per-day blocks."""
    from automations.icd_sales_board import board_read as BR
    from automations.terminated_reps import board as BD
    wk = BR.parse_week(grid, tab)
    lay = BD.find_layout(grid)
    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for r in lay.roster_rows:
        raw = str(BD._cell(grid, r, lay.name_col) or "").strip()
        if not raw or raw.lower().startswith("total"):
            continue
        per_day = {}
        for blk in wk.days:
            per_day[blk.day] = {m: str(BD._cell(grid, r, c) or "").strip()
                                for m, c in blk.measures}
        out[PEO.key(raw)] = per_day
    return out


def week_tabs(titles: List[str], year: int) -> Dict[dt.date, str]:
    """{week-ending Sunday: tab title} for every 'Sales Board WE m.d' tab."""
    out: Dict[dt.date, str] = {}
    for t in titles:
        m = WEEK_TAB.match(t.strip())
        if not m:
            continue
        try:
            d = dt.date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if d.weekday() == 6:                     # only real Sundays
            out[d] = t
    return out


@dataclass
class WeekSales:
    week: dt.date
    tab: str
    by_person: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def get(self, name: str, measure: str) -> Optional[str]:
        row = self.by_person.get(PEO.key(name))
        if not row:
            return None
        v = str(row.get(measure, "")).strip()
        return v or None


def read_week(grid: List[List[str]], tab: str, week: dt.date) -> WeekSales:
    from automations.icd_sales_board import board_read as BR
    wk = BR.parse_week(grid, tab)
    ws = WeekSales(week=week, tab=tab)
    for rep in wk.reps:
        ws.by_person[PEO.key(rep["name"])] = rep["values"]
    return ws


def cells_for(name: str, ws: WeekSales):
    """[(row label, value, source)] for one person in one week."""
    out = []
    for label, measures in SALES.items():
        for measure in measures:
            v = ws.get(name, measure)
            if v is None or v == "-":
                continue
            if re.fullmatch(r"-?\d+(\.\d+)?", v):
                f = float(v)
                v = str(int(f)) if abs(f - round(f)) < 1e-9 else v
            out.append((label, v, f"{ws.tab!r} {measure}"))
            break
    return out
