"""Read a sales board in Raf's format.

Raf's "Alphalete SALES BOARD 2025" is the template every ICD board copies, so
this parses that shape once instead of each surface re-deriving it. Everything
is found by LABEL — the header row by its 'Total Apps' cell, the rep block by
where it ends at 'TOTALS', the summary by its row labels — because the template
shifts between weeks (rows 74-85 on one tab are not rows 74-85 on another).

Read-only. Nothing here writes.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

WEEK_TAB_RE = re.compile(r"^Sales Board WE\s+(\d{1,2})\.(\d{1,2})$", re.I)
LINEUP_TAB_RE = re.compile(r"^Line Up WE\s+(\d{1,2})\.(\d{1,2})$", re.I)

# Tenure/status the field types into the NAME cell. Parsed out so the clean name
# can be matched against Tableau, and so the annotation becomes real data.
# ONLY known codes are stripped. A looser pattern ate real nicknames — "Jaylen
# (Ash) Walker" became "Jaylen Walker" — so an unrecognised parenthetical stays
# in the name and shows up as a match failure we can see, rather than a silently
# altered name we cannot.
_ANNOT = re.compile(r"\s*\(\s*(Wk\s*\d+|NC|BO)\s*\)\s*", re.I)

TOTALS_LABEL = "totals"
HEADER_CELL = "total apps"
# Col C is the LABEL column throughout: rep names, 'TOTALS', the summary row
# labels and the history week labels all live there. Col B is only the rank
# number, and col A only carries an occasional group label ('FIBER'/'ENERGY').
LABEL_COL = 3
GROUP_COL = 1


def _c(g, r, col):
    """1-indexed cell."""
    return g[r - 1][col - 1] if r - 1 < len(g) and col - 1 < len(g[r - 1]) else ""


def clean_name(raw: str) -> tuple:
    """('Anthony Vargas', ['Wk 2']) — the name Tableau knows, plus its tags.

    The board crams name + tenure + status into one cell. Matching on the raw
    string fails the moment someone is promoted from (Wk 2) to (Wk 3), so split
    them and match on the name alone."""
    tags = [m.strip() for m in _ANNOT.findall(raw or "")]
    return _ANNOT.sub(" ", raw or "").strip(), tags


# The daily blocks live far to the right (col Z onward on Raf's board): one
# block per weekday, each repeating the measure set and ending in 'Roll Call'
# — the daily attendance mark. Found by scanning the banner row for day names
# so a board with different column positions still parses.
_DAYS = ["MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"]
_DAY_ALIASES = {"MON": "Monday", "TUES": "Tuesday", "WED": "Wednesday",
                "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday",
                "SUN": "Sunday"}
ROLL_CALL = "roll call"

# Per-rep attribute columns, also on the banner row, after the day blocks.
# These already hold what an owner needs to set — no parallel store required.
ATTR_TENURE = "field status"
ATTR_TEAM = "team"
ATTR_LEVEL = "leadership status"
ATTR_START = "start date"
ATTR_TERM = "termination date"
ATTR_CAMPAIGN = "campaign"


@dataclass
class DayBlock:
    day: str                      # 'Monday'
    daynum: str = ""              # day-of-month from the row below the banner
    measures: list = field(default_factory=list)   # [(name, 1-indexed col)]
    roll_call_col: int = 0


@dataclass
class BoardWeek:
    tab: str
    week_label: str = ""          # the C3 header, e.g. 'WE 8/17- 8/23'
    measures: list = field(default_factory=list)   # this-week measure names
    reps: list = field(default_factory=list)       # [{name, tags, values{}}]
    totals: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)    # {group: {label: value}}
    history: list = field(default_factory=list)    # [(week label, [values])]
    days: list = field(default_factory=list)       # [DayBlock]
    attr_cols: dict = field(default_factory=dict)  # {lowered label: col}
    teams: dict = field(default_factory=dict)      # {team: goal + averages}

    @property
    def rep_count(self) -> int:
        return len(self.reps)

    @property
    def day_names(self) -> list:
        return [d.day for d in self.days]


def header_row(g) -> int:
    for r in range(1, min(len(g), 40) + 1):
        row = [(c or "").strip().lower() for c in g[r - 1]]
        if HEADER_CELL in row:
            return r
    raise ValueError("no header row carrying 'Total Apps'")


def totals_row(g, start: int) -> int:
    for r in range(start + 1, len(g) + 1):
        if (_c(g, r, LABEL_COL) or "").strip().lower() == TOTALS_LABEL:
            return r
    raise ValueError("no 'TOTALS' row below the header")


def parse_week(g, tab: str) -> BoardWeek:
    """Parse one 'Sales Board WE m.d' grid."""
    hr = header_row(g)
    tr = totals_row(g, hr)
    hdr = [(c or "").strip() for c in g[hr - 1]]

    # This week's measures start at 'Total Apps' and stop where LAST week's
    # block begins. The boundary comes from the banner row above the header
    # ("RUNNING WEEK TOTALS" | "LAST WEEK'S TOTALS"), NOT from spotting a
    # repeated measure name: last week's block leads with 'APPS' where this
    # week's leads with 'Total Apps', so a repeat-check sails straight past the
    # boundary and reports last week's total as this week's.
    start = next(i for i, c in enumerate(hdr) if c.lower() == HEADER_CELL)
    stop = len(hdr)
    for r in range(1, hr):
        for i, c in enumerate(g[r - 1]):
            if "last week" in (c or "").strip().lower() and i > start:
                stop = min(stop, i)
    measures, seen = [], set()
    for i in range(start, stop):
        name = hdr[i]
        if not name:
            break
        if name.lower() in seen:          # belt and braces
            break
        seen.add(name.lower())
        measures.append((name, i + 1))

    days = _day_blocks(g, hr)
    attr_cols = _attr_cols(g, hr)
    last_measures = _banner_span_measures(g, hr, "last week")

    reps = []
    for r in range(hr + 1, tr):
        raw = (_c(g, r, LABEL_COL) or "").strip()
        if not raw:
            continue
        name, tags = clean_name(raw)
        if not name:
            continue
        vals = {m: (_c(g, r, col) or "").strip() for m, col in measures}
        daily = {}
        for d in days:
            daily[d.day] = {
                "values": {m: (_c(g, r, col) or "").strip()
                           for m, col in d.measures},
                "roll_call": ((_c(g, r, d.roll_call_col) or "").strip()
                              if d.roll_call_col else ""),
            }
        attrs = {label: (_c(g, r, col) or "").strip()
                 for label, col in attr_cols.items()}
        last = {m: (_c(g, r, col) or "").strip() for m, col in last_measures}
        reps.append({"name": name, "raw": raw, "tags": tags, "values": vals,
                     "last_values": last, "daily": daily, "attrs": attrs})

    totals = {m: (_c(g, tr, col) or "").strip() for m, col in measures}

    # Summary blocks below TOTALS. The group label ('FIBER'/'ENERGY') sits in
    # col A on the block's FIRST row only and carries down; a block with no
    # group label is the whole office. Label in col C, value in col D.
    summary, group = {}, "ALL"
    for r in range(tr + 1, min(tr + 40, len(g) + 1)):
        a = (_c(g, r, GROUP_COL) or "").strip()
        label = " ".join((_c(g, r, LABEL_COL) or "").split())
        if a:
            group = a
        if not label or not re.search(r"reps|board|zero|%", label, re.I):
            continue
        val = (_c(g, r, LABEL_COL + 1) or "").strip()
        if val:
            summary.setdefault(group, {})[label] = val

    # History rows — a col-C label shaped like a week range.
    history = []
    for r in range(tr + 1, len(g) + 1):
        b = (_c(g, r, LABEL_COL) or "").strip()
        if re.match(r"^WE\s+\d{1,2}/\d{1,2}", b, re.I):
            vals = [(_c(g, r, col) or "").strip() for _, col in measures]
            history.append((b, vals))

    return BoardWeek(tab=tab, week_label=(_c(g, hr, LABEL_COL) or "").strip(),
                     measures=[m for m, _ in measures], reps=reps,
                     totals=totals, summary=summary, history=history,
                     days=days, attr_cols=attr_cols, teams=parse_teams(g))


TEAMS_LABEL = "teams"
TEAM_TOTALS_KEY = "__TOTALS__"
# The averages block sits far right of the Teams table, keyed by its own
# headers so a column insert can't silently shift what gets read.
_TEAM_AVG_HEADERS = {
    "team weekly goal": "goal",
    "total units avg": "units_avg",
    "new int avg": "new_int_avg",
    "lw total units avg": "lw_units_avg",
    "lw new int avg": "lw_new_int_avg",
    "active reps": "active_reps",
}


def parse_teams(g) -> dict:
    """{team name: {goal, units_avg, new_int_avg, lw_*}} from the Teams block.

    Raf's board carries a second table further down whose col-C header is
    literally 'Teams', with per-team weekly goal and averages out to the right.
    The office-wide line is 'Alphaletes TOTALS'; it is returned under
    TEAM_TOTALS_KEY so a caller can show it when no team is selected."""
    banner = None
    for r in range(1, len(g) + 1):
        if (_c(g, r, LABEL_COL) or "").strip().lower() == TEAMS_LABEL:
            banner = r
            break
    if banner is None:
        return {}

    cols = {}
    for i, cell in enumerate(g[banner - 1]):
        key = _TEAM_AVG_HEADERS.get(" ".join((cell or "").split()).lower())
        if key:
            cols[key] = i + 1
    if not cols:
        return {}

    # The Teams block repeats the board's own layout: CURRENT WEEK, LAST WEEK
    # and PVS WEEK measure sets, headed on the row below the banner. Grab this
    # week's 'Total Units' so a per-team week-over-week line can be built by
    # reading the same cell on each week's tab.
    sub_raw = g[banner] if banner < len(g) else []
    sub = [(c or "").strip().lower() for c in sub_raw]
    try:
        cols["units"] = sub.index("total units") + 1
    except ValueError:
        pass

    # Every CURRENT-WEEK measure for the team, so a per-team trend can plot any
    # of them and not just total units. The block repeats the measure set for
    # LAST and PVS week, so stop at the first repeat.
    measure_cols, seen = {}, set()
    start = cols.get("units")
    if start:
        for c in range(start, len(sub_raw) + 1):
            name = " ".join((sub_raw[c - 1] or "").split())
            if not name:
                break
            if name.lower() in seen:
                break
            seen.add(name.lower())
            measure_cols[name] = c

    out: dict = {}
    blanks = 0
    for r in range(banner + 1, min(banner + 60, len(g) + 1)):
        name = " ".join((_c(g, r, LABEL_COL) or "").split())
        vals = {k: (_c(g, r, c) or "").strip() for k, c in cols.items()}
        vals["measures"] = {m: (_c(g, r, c) or "").strip()
                            for m, c in measure_cols.items()}
        if not name:
            blanks += 1
            if blanks >= 4 and not any(vals.values()):
                break
            continue
        blanks = 0
        if name.lower().endswith("totals"):
            out[TEAM_TOTALS_KEY] = vals
            continue
        if any(vals.values()):
            out[name] = vals
    return out


def _banner_span_measures(g, hr: int, label_starts: str) -> list:
    """[(measure, col)] for one banner block, e.g. LAST WEEK'S TOTALS.

    The banner row marks each block's first column ("RUNNING WEEK TOTALS",
    "LAST WEEK'S TOTALS", "PRIOR WEEK'S TOTALS", then the day names), so a
    block runs from its own banner to whichever banner comes next. Located by
    label rather than a fixed column so the board can gain a measure without
    silently shifting what gets read."""
    br = _banner_row(g, hr)
    marks = sorted((i + 1, " ".join((c or "").split()).lower())
                   for i, c in enumerate(g[br - 1])
                   if (c or "").strip())
    start = end = None
    for n, (col, text) in enumerate(marks):
        if text.startswith(label_starts):
            start = col
            end = marks[n + 1][0] if n + 1 < len(marks) else col + 8
            break
    if start is None:
        return []
    hdr = [(c or "").strip() for c in g[hr - 1]]
    out = []
    for c in range(start, end):
        name = hdr[c - 1] if c - 1 < len(hdr) else ""
        if name:
            out.append((name, c))
    return out


def _banner_row(g, hr: int) -> int:
    """The row carrying 'RUNNING WEEK TOTALS' / the day names — above the
    header row."""
    for r in range(1, hr):
        row = " ".join((c or "") for c in g[r - 1]).lower()
        if "running week totals" in row or "mon" in row:
            return r
    return max(1, hr - 2)


def _day_blocks(g, hr: int) -> list:
    """One DayBlock per weekday, located by the day name on the banner row.

    Each block runs from its day name to the next one, repeating the measure
    set and ending in 'Roll Call'. Positions are read, never assumed, so a
    board that adds a measure still parses."""
    br = _banner_row(g, hr)
    banner = [(c or "").strip().upper() for c in g[br - 1]]
    starts = []
    for i, c in enumerate(banner):
        if c in _DAYS:
            starts.append((i + 1, _DAY_ALIASES[c]))
    if not starts:
        return []

    hdr = [(c or "").strip() for c in g[hr - 1]]
    out = []
    for n, (col, day) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else min(col + 9,
                                                               len(hdr) + 1)
        measures, roll = [], 0
        for c in range(col, end):
            name = hdr[c - 1] if c - 1 < len(hdr) else ""
            if not name:
                continue
            if name.strip().lower() == ROLL_CALL:
                roll = c
                continue
            measures.append((name, c))
        out.append(DayBlock(day=day,
                            daynum=(_c(g, br + 1, col) or "").strip(),
                            measures=measures, roll_call_col=roll))
    return out


def _attr_cols(g, hr: int) -> dict:
    """Per-rep attribute columns from the banner row (Team, Leadership Status,
    Start Date, …). Returned lowercased so callers match on a stable key."""
    br = _banner_row(g, hr)
    out = {}
    for i, c in enumerate(g[br - 1]):
        label = " ".join((c or "").split()).strip()
        if not label or label.upper() in _DAYS:
            continue
        low = label.lower()
        if low in {"running week totals", "last week's totals",
                   "prior week's totals"}:
            continue
        out.setdefault(low, i + 1)
    return out


def _safe_date(year: int, mo: int, day: int):
    try:
        return dt.date(year, mo, day)
    except ValueError:                     # e.g. 2/29 in a non-leap year
        return None


def week_tab_dates(titles: list, today: dt.date | None = None) -> list:
    """[(tab title, date)] for the week tabs, NEWEST FIRST.

    The tab names carry no year. Sorting on month/day alone is wrong the moment
    a board spans New Year — 'WE 12.27' would sort above 'WE 1.3' forever — so
    each tab is dated first (this year, or last year if that would be in the
    future), then sorted by the real date. A final pass walks the sorted list
    and pushes any tab that isn't strictly older than the one before it back a
    year, which keeps boards holding several years of tabs in order."""
    today = today or dt.date.today()
    dated = []
    for t in titles:
        m = WEEK_TAB_RE.match(t.strip())
        if not m:
            continue
        mo, day = int(m.group(1)), int(m.group(2))
        d = _safe_date(today.year, mo, day)
        if d is None:
            continue
        # the newest tab is often the CURRENT week, which ends a few days out
        if d > today + dt.timedelta(days=10):
            d = _safe_date(today.year - 1, mo, day) or d
        dated.append([t, d])

    dated.sort(key=lambda x: x[1], reverse=True)
    for i in range(1, len(dated)):
        while dated[i][1] >= dated[i - 1][1]:
            back = _safe_date(dated[i][1].year - 1, dated[i][1].month,
                              dated[i][1].day)
            if back is None:
                break
            dated[i][1] = back
    return [(t, d) for t, d in dated]


def week_tabs(titles: list, today: dt.date | None = None) -> list:
    """Week-tab titles, newest first."""
    return [t for t, _ in week_tab_dates(titles, today)]


def week_tab_labels(titles: list, today: dt.date | None = None) -> dict:
    """{tab title: '8/16/26'} — the DATE only.

    Deliberately not 'Week Ending 8/16/26': the words go on the picker's label,
    where they are said once, instead of on every option, where they push the
    date out of view in a narrow control (Megan 2026-08-17)."""
    return {t: f"{d.month}/{d.day}/{d.strftime('%y')}"
            for t, d in week_tab_dates(titles, today)}
