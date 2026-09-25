"""1st to 2nd Below the Mark -- the two-week board (Rafael, 2026-09-18).

Rafael's ask, after the single-day tab went live: lay it out like the Daily
Focus Report -- THIS week on the left, LAST week on the right, Monday to Friday
down the page -- so there is a record of who was under the bar on each day of
both weeks. Each day lists different people, because a different office slips
under 40% on a different day.

    row 1   THIS WEEK (week of 9/13)          |   LAST WEEK (week of 9/6)
    row 2   status: what this is, when it was last checked, what moved
    row 3   the tab's group banners           |   the same, again
    row 4   the tab's column headers          |   the same, again
            MONDAY 9/14 . 3 of 29 ...         |   MONDAY 9/7 . 2 of 31 ...
            <offices at or under 40%>         |   <offices at or under 40%>
            TUESDAY 9/15 ...                  |   TUESDAY 9/8 ...
            ...

Monday on the left sits on the same row as Monday on the right, so the two
weeks read across.

EVERY DAY IS RE-CHECKED ON EVERY RUN. An applicant the recruiter called on
Thursday can call back and book on Friday, which moves THURSDAY's number after
Thursday is over. So each run pulls all five days of both weeks fresh from
AppStream and the ARS REPORT files -- nothing is carried over from the last
fill. When a number did move, the board says so:
    - a note on the retention cell: "Was 33% at the Thu 9/17 18:30 check"
    - a note on the owner cell for an office that is NEW on a day's list
    - the day's band names anyone who climbed back ABOVE 40% and so dropped off
    - the status line counts how many moved
The "last check" is read back off this tab itself before it is rewritten, so it
works the same from the mini or from Windows -- there is no state file.

WHERE THE LOOK COMES FROM. This tab is generated end to end and is rebuilt on
every run -- do not format it by hand, it will not survive. Its look is copied
from the TEMPLATE tab (TEMPLATE_TAB): the group banner row, the header
row, the first data row's colours, and the column widths. Restyle THAT tab and
the next board run picks it up. The live tab itself is only read, never written.

Run:
    python -m automations.first_to_second_below_mark.board --dry-run
    python -m automations.first_to_second_below_mark.board             # writes the board tab
    python -m automations.first_to_second_below_mark.board --all       # every office, for checking
    python -m automations.first_to_second_below_mark.board --week 9/13 # which week is "this week"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.first_to_second_below_mark import appstream as apst
from automations.first_to_second_below_mark import ars_reports as ars
from automations.first_to_second_below_mark import columns as cols
from automations.first_to_second_below_mark import office_tz as tz
from automations.first_to_second_below_mark import run as rep
from automations.first_to_second_below_mark import source as src

# THE production tab since 2026-09-18 (Eve: "que esta sea la tab de
# produccion"). It was built as '... PREVIEW'; the original tab of this name
# became '1st to 2nd below the mark (old)'.
BOARD_TAB = "1st to 2nd below the mark"
# The board's look is copied from this tab (banners, headers, colours,
# widths); it holds no data and is only read. Renamed from '... SANDBOX' on
# 2026-09-21 (Eve: a tab called SANDBOX read as a test tab). The old name is
# still accepted so a rename and a deploy never have to land in the same
# minute. NOT rep.SANDBOX_TAB on purpose: sandbox.py --refresh DELETES the
# tab of that name and re-copies it.
TEMPLATE_TAB = "1st to 2nd below the mark TEMPLATE"
TEMPLATE_TAB_OLD = rep.SANDBOX_TAB
# The same board cut down to the offices of ONE pass (one time zone's 11:00 or
# 6:30 PM), which is what the picture is taken from. Generated like the board;
# it is kept HIDDEN (Eve, 2026-09-21: a clean workbook); a hidden tab exports as a
# blank page, so board_shot shows it just for the export and hides it again.
PICTURE_TAB = "1st to 2nd below the mark (picture)"
# Every office's numbers as of the last time that office was pulled, so a pass
# that pulls only one zone can still rebuild the whole board. Hidden, generated.
DATA_TAB = "1st to 2nd below the mark DATA"

# What the report measures, in words, on top of every board and picture:
# Rafael (2026-09-21) wanted it impossible to miss what the numbers are.
REPORT_TITLE = "RETENTION: FIRST SHOWED UP → BOOKED SECOND"

# Monday to FRIDAY (Eve, 2026-09-24). Saturday was added on 2026-09-21 with
# no request from Rafael behind it, and taken back out. The ARS REPORT files
# stop at Friday anyway. The launchd agent still fires on Saturdays; pick_pass
# sends nothing then. (Was: Saturday's qualified/answered columns stayed
# blank and only C/D/E fill.
WEEK_DAYS = list(ars.DAYS)

TITLE_ROW, STATUS_ROW, BANNER_ROW, HEADER_ROW = 1, 2, 3, 4
FIRST_BODY_ROW = 5
GAP_COLS = 1                              # blank column between the two weeks

# Eve's hand edits on the PREVIEW (2026-09-18), kept on every rebuild:
#   - the day bands are taller than the office rows, so the day reads first
#   - rows 3 and 4 are ONE cell in every column that has no group banner above
#     it (A-F and R-W): the header sits in a two-row box, and only the
#     QUALIFIED / ANSWERED groups keep the banner-over-header split.
DAY_ROW_PX = 31
ROW_PX = 21
TITLE_ROW_PX = 36
HEADER_ROW_PX = 48          # only if the template's own height cannot be read

DAY_BG = {"red": 0.263, "green": 0.263, "blue": 0.263}
WEEK_BG = {"red": 0.4, "green": 0.4, "blue": 0.4}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
MUTED = {"red": 0.4, "green": 0.4, "blue": 0.4}


# ------------------------------------------------------------------ the dates
def week_label(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def this_week_start(today: dt.date) -> dt.date:
    """The Sunday that starts the week the board calls THIS week.

    On a Sunday the new week has no weekday in it yet, so the board keeps the
    week that just ended on the left rather than showing five empty days."""
    if today.weekday() == 6:
        today -= dt.timedelta(days=1)
    return apst.current_week_start(today)


def day_date(week_start: dt.date, day: str) -> dt.date:
    return week_start + dt.timedelta(days=WEEK_DAYS.index(day) + 1)


# ----------------------------------------------------------- one day's result
@dataclass
class DayResult:
    day: str
    date: dt.date
    rows: List[list] = field(default_factory=list)       # listed, worst first
    all_rows: List[list] = field(default_factory=list)   # every office, unfiltered
    interviewed: int = 0                                 # offices with interviews
    future: bool = False
    today: bool = False                                  # still being worked
    risen: List[str] = field(default_factory=list)       # climbed back above the mark
    flagged: List[str] = field(default_factory=list)     # owners at or under the mark THIS day


@dataclass
class WeekResult:
    label: str
    start: dt.date
    days: Dict[str, DayResult] = field(default_factory=dict)
    missing: Optional[str] = None                        # why the week is blank
    totals: List[list] = field(default_factory=list)     # one row per listed office, the week summed
    through: Optional[dt.date] = None                    # last day the totals cover


# ----------------------------------------------------------------- the pull
def _assemble(owner: src.Owner, headers: List[str], as_row: Optional[dict],
              day_data: Optional[ars.OwnerDay]) -> list:
    col = cols.resolve(headers)
    row = [""] * len(headers)

    def put(fld, value):
        if fld in col and value is not None:
            row[col[fld]] = value

    put("owner", owner.name)
    put("goal", owner.goal)
    for fld, value in (as_row or {}).items():
        put(fld, value)
    if day_data is not None:
        put("interviewer", day_data.interviewer_label or None)
        for fld in ("qualified", "disqualified", "declined", "qualified_ret",
                    "declined_ret", "ab_qualified", "booked", "not_contacted",
                    "booked_ret", "not_contacted_ret"):
            put(fld, getattr(day_data, fld))
    return row


def _with_network_retry(fn, *, logfn=print, what: str = "", attempts: int = 3,
                        wait: float = 15.0):
    """fn(), retried on a dropped connection or timeout.

    fill's own retry covers Sheets' 429 and 5xx answers but not a request
    that never got an answer at all -- the 'Connection aborted / Operation
    timed out' the mini hits now and then. LookupError is a real answer (no
    box, no tab) and goes straight through."""
    import time
    import requests
    for i in range(attempts):
        try:
            return fn()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                TimeoutError) as exc:
            if i == attempts - 1:
                raise
            logfn(f"  .. {what}: {type(exc).__name__}, retrying in {wait:.0f}s")
            time.sleep(wait)


RowKey = Tuple[str, str, str]                           # (week label, day, owner)


def fetch_rows(weeks: List[src.Week], starts: List[dt.date], headers: List[str], *,
               today: dt.date, use_appstream: bool = True, refresh_index: bool = False,
               only: Optional[set] = None, logfn=print) -> Tuple[Dict[RowKey, list], List[str]]:
    """{(week, day, owner): row} for every day that has happened, pulled fresh.

    `only` limits the pull to those owners (one time zone's pass); None pulls
    everybody."""
    notes: List[str] = []
    labels = [w.label for w in weeks]

    owner_weeks: Dict[str, List[str]] = {}
    for w in weeks:
        for o in w.owners:
            if only is None or o.name in only:
                owner_weeks.setdefault(o.name, []).append(w.label)

    as_data: Dict[str, Dict[str, Dict[str, dict]]] = {}
    if use_appstream and owner_weeks:
        try:
            as_data, gaps = apst.fetch_weeks(owner_weeks, days=WEEK_DAYS, logfn=logfn)
            notes.extend(gaps)
        except Exception as exc:                          # noqa: BLE001
            notes.append(f"AppStream unavailable: {type(exc).__name__}: {exc}")
            logfn(f"  !! AppStream unavailable ({type(exc).__name__}: {exc})")
    elif not use_appstream:
        logfn("  --no-appstream: C/D/E left blank")

    # ARS REPORT: one read per owner covers both weeks and all five days.
    index = ars._index(logfn=logfn, refresh=refresh_index)
    aliases = ars.load_aliases()
    to_ars = {lab: ars.ars_week_label(lab, year_hint=s.year) for lab, s in zip(labels, starts)}
    ars_data: Dict[Tuple[str, str], Dict[str, ars.OwnerDay]] = {}
    books: Dict[str, object] = {}
    tabs: Dict[str, Dict[str, object]] = {}      # workbook -> {tab title: worksheet}
    for owner, wks in owner_weeks.items():
        hit = ars.find_tab(owner, index, aliases)
        if hit is None:
            notes.append(f"{owner}: no ARS REPORT tab")
            continue
        workbook, tab = hit

        def read():
            if workbook not in books:
                books[workbook] = fill.open_by_key(ars.ARS_WORKBOOKS[workbook])
                tabs[workbook] = {w.title.strip().lower(): w
                                  for w in books[workbook].worksheets()}
            return ars.read_owner_weeks(books[workbook], tab, owner, workbook,
                                        [to_ars[w] for w in wks],
                                        ws=tabs[workbook].get(tab.strip().lower()))
        try:
            got = _with_network_retry(read, logfn=logfn, what=owner)
        except LookupError as exc:
            notes.append(str(exc))
            continue
        except Exception as exc:                          # noqa: BLE001
            # One owner's read must not throw away the whole sweep -- the
            # AppStream pass before it takes the better part of ten minutes
            # (2026-09-18 07:35: a single Sheets timeout killed the first run).
            notes.append(f"{owner}: ARS REPORT read failed ({type(exc).__name__}: {exc})")
            continue
        for w in wks:
            if to_ars[w] in got:
                ars_data[(owner, w)] = got[to_ars[w]]
            else:
                notes.append(f"{owner}: no {to_ars[w]} box in {tab!r}")

    rows: Dict[RowKey, list] = {}
    for w, start in zip(weeks, starts):
        for o in w.owners:
            if o.name not in owner_weeks:
                continue
            for day in WEEK_DAYS:
                if day_date(start, day) > today:
                    continue
                as_row = ((as_data.get(w.label) or {}).get(day) or {}).get(o.name)
                ars_day = (ars_data.get((o.name, w.label)) or {}).get(day)
                rows[(w.label, day, o.name)] = _assemble(o, headers, as_row, ars_day)
    return rows, notes


def _n(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return ars._as_number(v) if isinstance(v, str) else None


def week_total(rows: List[list], headers: List[str]) -> list:
    """One office's days added up into one row (Rafael, 2026-09-24: "Total for
    the week" -- Monday to today combined, to see where the week sits).

    Counts are summed; every % is worked out again from the summed counts,
    never averaged -- a 0% day with one interview must not weigh as much as a
    60% day with ten. The same ratios the boxes use:
        retention        1st showed up booked 2nd / 1st interviews showed up
        qualified %      qualified / (qualified + disqualified + declined)
        declined %       (disqualified + declined) / the same
        booked %         booked / qualified (answered block)
        not contacted %  not contacted / qualified (answered block)"""
    col = cols.resolve(headers)
    out = [""] * len(headers)

    def cell(row, f):
        i = col.get(f)
        return row[i] if i is not None and i < len(row) else ""

    def total(f) -> Optional[float]:
        vals = [v for v in (_n(cell(r, f)) for r in rows) if v is not None]
        return sum(vals) if vals else None

    def put(f, v):
        if f in col and v is not None:
            out[col[f]] = v

    def ratio(num, den) -> Optional[float]:
        return num / den if num is not None and den else None

    put("owner", cell(rows[0], "owner") if rows else None)
    put("goal", next((cell(r, "goal") for r in rows if cell(r, "goal") != ""), None))
    names: List[str] = []
    for r in rows:
        for n in str(cell(r, "interviewer") or "").split(","):
            if n.strip() and n.strip() not in names:
                names.append(n.strip())
    put("interviewer", ", ".join(names) or None)
    sums = {f: total(f) for f in rep.COUNT_FIELDS}
    for f, v in sums.items():
        put(f, v)
    put("retention", ratio(sums.get("booked_2nd"), sums.get("first_showed")))
    screened = sum(sums.get(f) or 0 for f in ("qualified", "disqualified", "declined"))
    if sums.get("qualified") is not None:
        put("qualified_ret", ratio(sums["qualified"], screened))
    if sums.get("disqualified") is not None or sums.get("declined") is not None:
        put("declined_ret", ratio((sums.get("disqualified") or 0) + (sums.get("declined") or 0),
                                  screened))
    put("booked_ret", ratio(sums.get("booked"), sums.get("ab_qualified")))
    put("not_contacted_ret", ratio(sums.get("not_contacted"), sums.get("ab_qualified")))
    return out


def build_results(weeks: List[src.Week], starts: List[dt.date], headers: List[str],
                  rows: Dict[RowKey, list], *, today: dt.date, show_all: bool = False,
                  only: Optional[set] = None) -> List[WeekResult]:
    """The board's weeks and days out of the rows. `only` keeps just those
    owners (the picture of one pass).

    THE WHOLE WEEK FOR ANYONE WHO SLIPPED (Rafael, 2026-09-24): an office at
    or under the mark on ANY day of the week is shown on EVERY day of that
    week, so its Monday-to-today run reads down the page ("Isaiah is on for
    Monday, but we don't see him again for Tuesday"). Same order every day:
    worst week total first. Under the days goes the week's TOTAL: each of
    those offices with its days so far added up."""
    results = []
    col = cols.resolve(headers)
    shown_i = col.get("first_showed")
    owner_i = col.get("owner", 0)
    for w, start in zip(weeks, starts):
        wr = WeekResult(label=w.label, start=start)
        per_day: Dict[str, Dict[str, list]] = {}
        listed: List[str] = []
        for day in WEEK_DAYS:
            d = day_date(start, day)
            dr = DayResult(day=day, date=d, future=d > today, today=d == today)
            if not dr.future:
                dr.all_rows = [rows[(w.label, day, o.name)] for o in w.owners
                               if (w.label, day, o.name) in rows
                               and (only is None or o.name in only)]
                dr.interviewed = sum(
                    1 for r in dr.all_rows
                    if shown_i is not None and isinstance(r[shown_i], (int, float)) and r[shown_i])
                flagged = dr.all_rows if show_all else rep.below_the_mark(dr.all_rows, headers)
                dr.flagged = [str(r[owner_i]) for r in flagged]
                listed += [o for o in dr.flagged if o not in listed]
                per_day[day] = {str(r[owner_i]): r for r in dr.all_rows}
                wr.through = d
            wr.days[day] = dr
        totals = [week_total([per_day[day][o] for day in WEEK_DAYS
                              if o in per_day.get(day, {})], headers) for o in listed]
        wr.totals = rep.worst_first(totals, headers)
        order = [str(r[owner_i]) for r in wr.totals]
        for dr in wr.days.values():
            if not dr.future:
                dr.rows = [per_day[dr.day][o] for o in order if o in per_day[dr.day]]
        results.append(wr)
    return results


def pull(weeks: List[src.Week], starts: List[dt.date], headers: List[str], *,
         today: dt.date, use_appstream: bool = True, show_all: bool = False,
         refresh_index: bool = False, logfn=print) -> Tuple[List[WeekResult], List[str]]:
    """Every day of every week, from scratch."""
    rows, notes = fetch_rows(weeks, starts, headers, today=today, use_appstream=use_appstream,
                             refresh_index=refresh_index, logfn=logfn)
    return build_results(weeks, starts, headers, rows, today=today, show_all=show_all), notes


# ------------------------------------------------------------ the DATA store
# A pass pulls only the offices that are due, so the numbers of everybody else
# come from here: each office as of the last pass that pulled it. It lives in
# the workbook, not in a file, so the board rebuilds the same from any machine.
DATA_KEYS = ["Week", "Day", "Owner", "Pulled (CT)"]


def store_to_values(rows: Dict[RowKey, list], pulled: Dict[RowKey, str],
                    headers: List[str]) -> List[list]:
    out = [DATA_KEYS + list(headers)]
    order = {d: i for i, d in enumerate(WEEK_DAYS)}
    for key in sorted(rows, key=lambda k: (k[0], order.get(k[1], 9), k[2])):
        wk, day, owner = key
        out.append([wk, day, owner, pulled.get(key, "")] + list(rows[key]))
    return out


def store_from_values(values: List[list], headers: List[str]
                      ) -> Tuple[Dict[RowKey, list], Dict[RowKey, str]]:
    """Rows back out of the DATA tab, lined up with TODAY's headers by label,
    so a column added to the template does not shift every stored number."""
    rows: Dict[RowKey, list] = {}
    pulled: Dict[RowKey, str] = {}
    if not values:
        return rows, pulled
    head = [str(h) for h in values[0]]
    if head[:len(DATA_KEYS)] != DATA_KEYS:
        return rows, pulled
    stored = {cols.norm(h): i for i, h in enumerate(head) if i >= len(DATA_KEYS)}
    for v in values[1:]:
        if len(v) < 3 or not str(v[0]).strip():
            continue
        key = (str(v[0]), str(v[1]), str(v[2]))
        row = []
        for h in headers:
            i = stored.get(cols.norm(h))
            row.append(v[i] if i is not None and i < len(v) else "")
        rows[key] = row
        pulled[key] = str(v[3]) if len(v) > 3 else ""
    return rows, pulled


def read_store(sh, headers: List[str]) -> Tuple[Dict[RowKey, list], Dict[RowKey, str]]:
    try:
        ws = fill.worksheet_ci(sh, DATA_TAB)
    except Exception:                                     # noqa: BLE001
        return {}, {}
    return store_from_values(ws.get_all_values(value_render_option="UNFORMATTED_VALUE"),
                             headers)


def write_store(sh, rows: Dict[RowKey, list], pulled: Dict[RowKey, str],
                headers: List[str]) -> None:
    values = store_to_values(rows, pulled, headers)
    width = len(values[0])
    try:
        ws = fill.worksheet_ci(sh, DATA_TAB)
    except Exception:                                     # noqa: BLE001
        ws = sh.add_worksheet(title=DATA_TAB, rows=len(values) + 100, cols=width + 2)
        sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "hidden": True}, "fields": "hidden"}}]})
    if ws.row_count < len(values) or ws.col_count < width:
        ws.resize(rows=max(ws.row_count, len(values) + 100), cols=max(ws.col_count, width))
    ws.batch_clear([f"A1:{ars.a1col(max(ws.col_count, width))}{ws.row_count}"])
    ws.update(range_name=f"A1:{ars.a1col(width)}{len(values)}", values=values,
              value_input_option="RAW")


# ------------------------------------------------------- what the last fill said
@dataclass
class PriorFill:
    stamp: str = ""                                     # 'Thu 9/17 18:30'
    show_all: bool = False                              # that fill listed every office
    # (week label, day) -> {owner: retention} for the offices that were listed
    listed: Dict[Tuple[str, str], Dict[str, Optional[float]]] = field(default_factory=dict)


_STAMP_RE = re.compile(r"checked (\w{3} \d{1,2}/\d{1,2} \d{1,2}:\d{2})")
_WEEK_RE = re.compile(r"week of (\d{1,2}/\d{1,2})", re.I)


def read_prior(values: List[List], width: int, headers: List[str]) -> PriorFill:
    """Parse the board as the last run left it. Blank tab -> nothing to compare."""
    prior = PriorFill()
    if not values:
        return prior
    status = str(values[STATUS_ROW - 1][0]) if len(values) >= STATUS_ROW and values[STATUS_ROW - 1] else ""
    m = _STAMP_RE.search(status)
    prior.stamp = m.group(1) if m else ""
    prior.show_all = "every office" in status.lower()
    col = cols.resolve(headers)
    owner_i, pct_i = col.get("owner", 0), col.get("retention")
    for c0 in (0, width + GAP_COLS):
        title = str(values[0][c0]) if len(values[0]) > c0 else ""
        wm = _WEEK_RE.search(title)
        if not wm:
            continue
        wk, day = wm.group(1), None
        for row in values[FIRST_BODY_ROW - 1:]:
            first = str(row[c0]) if len(row) > c0 else ""
            head = first.split(" ", 1)[0]
            if head.isupper() and head.title() in WEEK_DAYS:
                day = head.title()
                continue
            if first.startswith(TOTAL_BAND):
                day = None                   # the week's total, not a day
                continue
            if not day or not first.strip() or pct_i is None:
                continue
            if first.startswith("No office"):
                continue                     # the "nobody under the mark" line
            pct = row[c0 + pct_i] if len(row) > c0 + pct_i else ""
            prior.listed.setdefault((wk, day), {})[first.strip()] = \
                pct if isinstance(pct, (int, float)) else ars._as_number(str(pct))
    return prior


def _pct(x) -> str:
    return f"{round(x * 100)}%" if isinstance(x, (int, float)) else "blank"


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(a * 100) == round(b * 100)
    return a == b


def compare(results: List[WeekResult], prior: PriorFill, headers: List[str]
            ) -> Dict[Tuple[str, str, str], Tuple[str, str]]:
    """{(week, day, owner): (field, note)} for everything that moved.

    Also fills DayResult.risen with the offices that were listed last time and
    are now above the mark. Days the last check never saw (they had not happened
    yet) are not compared: everything on them is new by definition."""
    notes: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
    # A fill that listed EVERY office (--all, a check run) is no baseline: every
    # office on it looks "listed", so all of them would read as moved.
    if not prior.stamp or prior.show_all:
        return notes
    col = cols.resolve(headers)
    owner_i, pct_i = col.get("owner", 0), col.get("retention")
    if pct_i is None:
        return notes
    for wr in results:
        for day, dr in wr.days.items():
            before = prior.listed.get((wr.label, day))
            # Today is still being worked, so of course it moves between checks;
            # what Rafael needs to see is an EARLIER day changing after the fact.
            if before is None or dr.future or dr.today:
                continue
            now_all = {str(r[owner_i]): r[pct_i] for r in dr.all_rows}
            now_listed = {str(r[owner_i]) for r in dr.rows}
            for owner in now_listed:
                if owner in before:
                    # No number last time is not a number that moved.
                    if (isinstance(before[owner], (int, float))
                            and not _same(before[owner], now_all.get(owner))):
                        notes[(wr.label, day, owner)] = (
                            "retention", f"{owner} (was {_pct(before[owner])})")
                elif owner in dr.flagged:
                    # On a day only because another day slipped is not news;
                    # slipping under the mark on it after the fact is.
                    notes[(wr.label, day, owner)] = ("owner", f"{owner} (new)")
            for owner, was in before.items():
                # Only a real number that is now over the mark. A blank then
                # ("no reading yet") or a blank now (no interviews) is not
                # someone climbing back.
                if (owner not in now_listed and isinstance(was, (int, float))
                        and isinstance(now_all.get(owner), (int, float))):
                    dr.risen.append(f"{owner} ({_pct(was)} -> {_pct(now_all.get(owner))})")
    return notes


# ------------------------------------------------------------------ the layout
def _band_text(dr: DayResult, show_all: bool, moved: Optional[List[str]] = None) -> str:
    head = f"{dr.day.upper()} {dr.date.month}/{dr.date.day}"
    if dr.today:
        # Early in the day an office with one interview and no callback yet
        # reads 0%; say the day is not finished so that is not taken as final.
        head += " (today, still moving)"
    if dr.future:
        return f"{head}  ·  not yet"
    if not dr.interviewed and not dr.rows:
        return f"{head}  ·  no interviews recorded"
    if show_all:
        text = f"{head}  ·  every office ({dr.interviewed} interviewed)"
    else:
        text = (f"{head}  ·  {len(dr.flagged)} of {dr.interviewed} offices that "
                f"interviewed at or under {rep.THRESHOLD:.0%}")
    # What moved since the last check goes IN the band, not in cell notes: a
    # note prints as a footnote in the DM picture, in huge type, and throws the
    # table's scale off (2026-09-18).
    if moved:
        text += "  ·  changed since last check: " + ", ".join(moved)
    if dr.risen:
        text += f"  ·  back above {rep.THRESHOLD:.0%}: " + ", ".join(dr.risen)
    return text


def _empty_text(dr: DayResult) -> str:
    if dr.future or not dr.interviewed:
        return ""
    return f"No office at or under {rep.THRESHOLD:.0%} this day."


@dataclass
class Layout:
    values: List[list]                                  # the whole grid
    band_rows: List[int]                                # 1-indexed
    data_rows: List[Tuple[int, int]]                    # (row, block start col 0-idx)
    message_rows: List[Tuple[int, int]]
    last_row: int
    cell_notes: List[Tuple[int, int, str]]              # (row, col 0-idx, note)


def lay_out(results: List[WeekResult], headers: List[str], status: str,
            notes: Dict[Tuple[str, str, str], Tuple[str, str]],
            show_all: bool) -> Layout:
    width = len(headers)
    total = width * len(results) + GAP_COLS * (len(results) - 1)
    col = cols.resolve(headers)
    owner_i = col.get("owner", 0)
    grid: List[list] = []

    def blank():
        return [""] * total

    titles = blank()
    for k, wr in enumerate(results):
        which = "THIS WEEK" if k == 0 else "LAST WEEK"
        mon, fri = day_date(wr.start, "Monday"), day_date(wr.start, WEEK_DAYS[-1])
        t = (f"{which}  ·  week of {wr.label}  ·  Mon {mon.month}/{mon.day} – "
             f"{fri:%a} {fri.month}/{fri.day}  ·  {REPORT_TITLE}")
        if wr.missing:
            t += f"  ·  {wr.missing}"
        titles[k * (width + GAP_COLS)] = t
    grid.append(titles)
    st = blank()
    st[0] = status
    grid.append(st)
    grid.append(blank())                 # banners: pasted from the template
    grid.append(blank())                 # headers: pasted from the template

    bands, data, msgs, cell_notes = [], [], [], []
    for day in WEEK_DAYS:
        band = blank()
        for k, wr in enumerate(results):
            moved = [note for (wk, d, _), (_, note) in notes.items()
                     if wk == wr.label and d == day]
            band[k * (width + GAP_COLS)] = _band_text(wr.days[day], show_all, moved)
        grid.append(band)
        bands.append(len(grid))
        height = max([len(wr.days[day].rows) for wr in results] + [1])
        for i in range(height):
            line = blank()
            for k, wr in enumerate(results):
                c0 = k * (width + GAP_COLS)
                dr = wr.days[day]
                if i < len(dr.rows):
                    line[c0:c0 + width] = dr.rows[i]
                    data.append((len(grid) + 1, c0))
                elif i == 0 and _empty_text(dr):
                    line[c0] = _empty_text(dr)
                    msgs.append((len(grid) + 1, c0))
            grid.append(line)

    # The week's TOTAL, under the last day (Rafael, 2026-09-24).
    band = blank()
    for k, wr in enumerate(results):
        band[k * (width + GAP_COLS)] = total_band_text(wr)
    grid.append(band)
    bands.append(len(grid))
    for i in range(max([len(wr.totals) for wr in results] + [1])):
        line = blank()
        for k, wr in enumerate(results):
            c0 = k * (width + GAP_COLS)
            if i < len(wr.totals):
                line[c0:c0 + width] = wr.totals[i]
                data.append((len(grid) + 1, c0))
            elif i == 0 and wr.through:
                line[c0] = f"No office at or under {rep.THRESHOLD:.0%} this week."
                msgs.append((len(grid) + 1, c0))
        grid.append(line)
    return Layout(values=grid, band_rows=bands, data_rows=data, message_rows=msgs,
                  last_row=len(grid), cell_notes=cell_notes)


TOTAL_BAND = "TOTAL FOR THE WEEK"


def total_band_text(wr: WeekResult) -> str:
    """'TOTAL FOR THE WEEK  ·  Mon 9/21 – Thu 9/24 combined  ·  7 offices ...'"""
    if wr.through is None:
        return f"{TOTAL_BAND}  ·  not yet"
    mon = day_date(wr.start, "Monday")
    span = f"Mon {mon.month}/{mon.day}"
    if wr.through != mon:
        span += f" – {wr.through:%a} {wr.through.month}/{wr.through.day}"
    n = len(wr.totals)
    return (f"{TOTAL_BAND}  ·  {span} combined  ·  {n} office{'s' if n != 1 else ''} "
            f"at or under {rep.THRESHOLD:.0%} on at least one day")


# --------------------------------------------------------------- the requests
def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def format_requests(sid: int, tsid: int, t_hrow: int, headers: List[str],
                    layout: Layout, n_blocks: int, widths: List[Optional[int]],
                    head_heights: Optional[List[Optional[int]]] = None) -> List[dict]:
    width = len(headers)
    total = width * n_blocks + GAP_COLS * (n_blocks - 1)
    starts = [k * (width + GAP_COLS) for k in range(n_blocks)]
    reqs: List[dict] = []

    # A clean slate: this tab is generated, every run rebuilds it.
    reqs.append({"unmergeCells": {"range": {"sheetId": sid}}})
    reqs.append({"updateCells": {"range": {"sheetId": sid},
                                 "fields": "userEnteredFormat,note"}})

    # The template's banner and header rows, once per week. Banners start at
    # column C: A of that row holds the live tab's own status line.
    # Every row back to the plain height first: the days land on different
    # rows from one run to the next, and a band's tall height would otherwise
    # stay behind on whatever office row takes its place.
    # Only the body: rows 3-4 take the template's heights below, because a
    # fixed 21px there cut the wrapped headers to their first word ('Not').
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": FIRST_BODY_ROW - 1,
                  "endIndex": max(layout.last_row + 60, 300)},
        "properties": {"pixelSize": ROW_PX}, "fields": "pixelSize"}})
    for row, px in ((BANNER_ROW, (head_heights or [None, None])[0]),
                    (HEADER_ROW, (head_heights or [None, None])[-1])):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": row - 1, "endIndex": row},
            "properties": {"pixelSize": px or HEADER_ROW_PX}, "fields": "pixelSize"}})
    col = cols.resolve(headers)
    # The columns before the first group banner get the two-row header box.
    boxed = col.get("qualified", 0)
    for c0 in starts:
        if boxed:
            reqs.append({"copyPaste": {
                "source": _rng(tsid, t_hrow - 1, t_hrow, 0, boxed),
                "destination": _rng(sid, BANNER_ROW - 1, BANNER_ROW, c0, c0 + boxed),
                "pasteType": "PASTE_NORMAL"}})
        reqs.append({"copyPaste": {
            "source": _rng(tsid, t_hrow - 2, t_hrow - 1, max(2, boxed), width),
            "destination": _rng(sid, BANNER_ROW - 1, BANNER_ROW, c0 + max(2, boxed), c0 + width),
            "pasteType": "PASTE_NORMAL"}})
        reqs.append({"copyPaste": {
            "source": _rng(tsid, t_hrow - 1, t_hrow, 0, width),
            "destination": _rng(sid, HEADER_ROW - 1, HEADER_ROW, c0, c0 + width),
            "pasteType": "PASTE_NORMAL"}})
        if boxed:
            reqs.append({"mergeCells": {
                "range": _rng(sid, BANNER_ROW - 1, HEADER_ROW, c0, c0 + boxed),
                "mergeType": "MERGE_COLUMNS"}})
    # Office rows wear the template's first data row.
    for r, c0 in layout.data_rows:
        reqs.append({"copyPaste": {
            "source": _rng(tsid, t_hrow, t_hrow + 1, 0, width),
            "destination": _rng(sid, r - 1, r, c0, c0 + width),
            "pasteType": "PASTE_FORMAT"}})

    def band(row, c0, c1, bg, size, italic=False, fg=WHITE):
        reqs.append({"mergeCells": {"range": _rng(sid, row - 1, row, c0, c1),
                                    "mergeType": "MERGE_ALL"}})
        reqs.append({"repeatCell": {"range": _rng(sid, row - 1, row, c0, c1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": bg, "verticalAlignment": "MIDDLE",
                "horizontalAlignment": "LEFT", "wrapStrategy": "CLIP",
                "textFormat": {"fontFamily": rep.FONT, "fontSize": size, "bold": not italic,
                               "italic": italic, "foregroundColor": fg}}},
            "fields": "userEnteredFormat(backgroundColor,verticalAlignment,"
                      "horizontalAlignment,wrapStrategy,textFormat)"}})

    for c0 in starts:
        band(TITLE_ROW, c0, c0 + width, rep.BANNER_BG, 14)
    band(STATUS_ROW, 0, total, rep.STATUS_BG, 10, italic=True, fg={"red": 0, "green": 0, "blue": 0})
    for r in layout.band_rows:
        for c0 in starts:
            band(r, c0, c0 + width, DAY_BG, 11)
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r - 1, "endIndex": r},
            "properties": {"pixelSize": DAY_ROW_PX}, "fields": "pixelSize"}})
    for r, c0 in layout.message_rows:
        reqs.append({"repeatCell": {"range": _rng(sid, r - 1, r, c0, c0 + 1),
            "cell": {"userEnteredFormat": {"wrapStrategy": "OVERFLOW_CELL",
                "textFormat": {"fontFamily": rep.FONT, "italic": True,
                               "foregroundColor": MUTED}}},
            "fields": "userEnteredFormat(wrapStrategy,textFormat)"}})

    # The coloured columns start WHITE. The template row carries a fixed fill
    # under them (green under Qualified Retention, yellow under the retention),
    # so a blank cell read as a good number. Every real value gets its colour
    # from the conditional rules instead -- each band has a red catch-all, so
    # nothing with a number can stay white.
    cf_cols = [col[f] for f in ("retention", "qualified_ret", "declined_ret",
                                "booked_ret", "not_contacted_ret") if f in col]
    for r, c0 in layout.data_rows:
        for i in cf_cols:
            reqs.append({"repeatCell": {"range": _rng(sid, r - 1, r, c0 + i, c0 + i + 1),
                "cell": {"userEnteredFormat": {"backgroundColor": WHITE}},
                "fields": "userEnteredFormat.backgroundColor"}})

    # Number formats by field, on office rows only.
    for r, c0 in layout.data_rows:
        for fields_, pattern, kind in ((rep.PERCENT_FIELDS, "0%", "PERCENT"),
                                       (rep.COUNT_FIELDS, "0", "NUMBER")):
            for f in fields_:
                i = col.get(f)
                if i is None:
                    continue
                reqs.append({"repeatCell": {"range": _rng(sid, r - 1, r, c0 + i, c0 + i + 1),
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                    "fields": "userEnteredFormat.numberFormat"}})

    for r, c, note in layout.cell_notes:
        reqs.append({"updateCells": {"range": _rng(sid, r - 1, r, c, c + 1),
                                     "rows": [{"values": [{"note": note}]}], "fields": "note"}})

    # Widths: the template's, both weeks; the gap column narrow.
    for k, c0 in enumerate(starts):
        for i, px in enumerate(widths[:width]):
            if px:
                reqs.append({"updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS",
                              "startIndex": c0 + i, "endIndex": c0 + i + 1},
                    "properties": {"pixelSize": px}, "fields": "pixelSize"}})
        if k:
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS",
                          "startIndex": c0 - GAP_COLS, "endIndex": c0},
                "properties": {"pixelSize": 24}, "fields": "pixelSize"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": TITLE_ROW_PX}, "fields": "pixelSize"}})
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": HEADER_ROW}},
        "fields": "gridProperties.frozenRowCount"}})
    return reqs


def cf_requests(sid: int, existing: List[dict], headers: List[str],
                n_blocks: int, last_row: int) -> List[dict]:
    """The single-day tab's colour rules, once per week. Every rule on this tab
    is ours, so the old ones all go first."""
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
            for i in reversed(range(len(existing)))]
    width = len(headers)
    index = 0
    for k in range(n_blocks):
        shifted = [""] * (k * (width + GAP_COLS)) + list(headers)
        for column, rules in rep.cf_plan(shifted, FIRST_BODY_ROW):
            rng = _rng(sid, FIRST_BODY_ROW - 1, last_row, column, column + 1)
            cell = f"{ars.a1col(column + 1)}{FIRST_BODY_ROW}"
            for formula, bg, fg in rules:
                # Only a NUMBER gets a colour. The filler rows under the shorter
                # week hold empty text, and Sheets ranks text above every number,
                # so '>=0.4' read true there and painted blank cells yellow/green.
                formula = f"=AND(ISNUMBER({cell}),{formula.lstrip('=')})"
                reqs.append({"addConditionalFormatRule": {"index": index, "rule": {
                    "ranges": [rng],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA",
                                      "values": [{"userEnteredValue": formula}]},
                        "format": {"backgroundColor": bg,
                                   "textFormat": {"bold": True, "foregroundColor": fg}}}}}})
                index += 1
    return reqs


# ------------------------------------------------------------------- the run
def _template(sh, logfn=print):
    """(worksheet, header row, headers, column widths) from the live tab."""
    try:
        tws = fill.worksheet_ci(sh, TEMPLATE_TAB)
    except Exception:                                     # noqa: BLE001
        tws = fill.worksheet_ci(sh, TEMPLATE_TAB_OLD)
    top = tws.get("A1:AZ25")
    hrow = rep.find_header_row(top)
    if hrow is None:
        raise SystemExit(f"{tws.title!r}: no {rep.OWNER_HEADER!r} header row")
    headers = list(top[hrow - 1])
    while headers and not rep._norm(headers[-1]):
        headers.pop()
    # The board stops before 'Office to Fill out report for': a working column
    # the report never fills, and wide enough to crowd everything else out.
    office = cols.resolve(headers).get("office")
    if office is not None:
        headers = headers[:office]
    meta = sh.fetch_sheet_metadata({
        "ranges": [f"'{tws.title}'!A{hrow - 1}:{ars.a1col(len(headers))}{hrow}"],
        "fields": "sheets(properties.sheetId,data(columnMetadata.pixelSize,"
                  "rowMetadata.pixelSize))"})
    widths: List[Optional[int]] = []
    heights: List[Optional[int]] = []
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] == tws.id:
            for d in s.get("data", []):
                widths = [c.get("pixelSize") for c in d.get("columnMetadata", [])]
                heights = [r.get("pixelSize") for r in d.get("rowMetadata", [])]
    logfn(f"  template: {tws.title!r}, headers on row {hrow}, {len(headers)} columns")
    return tws, hrow, headers, widths, heights


def _board_ws(sh, tab: str, rows: int, cols_: int):
    try:
        ws = fill.worksheet_ci(sh, tab)
    except Exception:                                     # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=max(rows, 300), cols=max(cols_, 40))
        return ws, True
    if ws.row_count < rows or ws.col_count < cols_:
        ws.resize(rows=max(ws.row_count, rows), cols=max(ws.col_count, cols_))
    return ws, False


def _write_tab(sh, tab: str, tws, t_hrow: int, headers: List[str], widths, head_heights,
               layout: Layout, n_blocks: int, logfn=print) -> None:
    width = len(headers)
    total_cols = n_blocks * width + GAP_COLS * (n_blocks - 1)
    bws, created = _board_ws(sh, tab, layout.last_row + 60, total_cols)
    if not created:
        # Unmerge BEFORE writing. Last run's day bands are merged across a whole
        # week, and a value written into a merged cell that is not its top-left
        # one is silently dropped -- the first live run lost every number on the
        # row where the test run had put Tuesday's band (2026-09-18).
        sh.batch_update({"requests": [{"unmergeCells": {"range": {"sheetId": bws.id}}}]})
        bws.batch_clear([f"A1:{ars.a1col(max(bws.col_count, total_cols))}{bws.row_count}"])
    bws.update(range_name=f"A1:{ars.a1col(total_cols)}{layout.last_row}",
               values=layout.values, value_input_option="RAW")
    sh.batch_update({"requests": format_requests(bws.id, tws.id, t_hrow, headers, layout,
                                                 n_blocks, widths, head_heights)})
    meta = sh.fetch_sheet_metadata()
    existing = next((s.get("conditionalFormats", []) for s in meta["sheets"]
                     if s["properties"]["sheetId"] == bws.id), [])
    sh.batch_update({"requests": cf_requests(bws.id, existing, headers, n_blocks,
                                             layout.last_row)})
    logfn(f"  wrote {layout.last_row} rows to {tab!r}")


def borrow_roster(weeks: List[src.Week], missing: List[Optional[str]]) -> None:
    """This week not on the source tab yet -> check LAST week's offices, with
    TODAY's numbers.

    The source tab's weekly block (which offices, and each one's goal) is added
    by hand, and on a Monday it is often not there yet -- so Monday's list came
    out empty while AppStream already had the day (2026-09-21). Only the office
    list and goals are borrowed; every number is still pulled for the day it
    belongs to. An office that opened this week is missing until the block is
    added, which the week's title says."""
    if weeks and not weeks[0].owners and len(weeks) > 1 and weeks[1].owners:
        weeks[0] = src.Week(label=weeks[0].label, header_row=0,
                            owners=list(weeks[1].owners))
        missing[0] = (f"office list borrowed from week of {weeks[1].label} "
                      f"(this week not on {src.SOURCE_TAB!r} yet)")


def pick_pass(roster: List[str], now: dt.datetime, *, due: bool = False,
              zone: Optional[str] = None) -> Tuple[Optional[set], str, List[str]]:
    """(owners in this pass or None for all, the pass's name, its zone labels).

    --due takes whoever's local 11:00 AM or 6:30 PM it is right now; --zone
    takes one zone by hand (a re-run, a preview); neither takes everybody."""
    if zone:
        want = zone.strip().title()
        picked = [o for o in roster if tz.label(tz.zone_or_fallback(o)[0]) == want]
        return set(picked), f"{want} offices", [want]
    if due and now.weekday() >= len(WEEK_DAYS):
        return set(), "", []                      # weekend: no post (Mon-Fri)
    if due:
        # ONE post per slot with every time zone in it (Rafael, 2026-09-24):
        # due when the LAST zone reaches its 11:00 AM / 6:30 PM, and then every
        # office is pulled again -- the zones that got there earlier are
        # re-checked, not reused from their own hour.
        slot = tz.last_zone_slot(roster, now)
        if slot is None:
            return set(), "", []
        zones = {tz.zone_or_fallback(o)[0] for o in roster} or {tz.FALLBACK_ZONE}
        last = min(zones, key=lambda z: now.astimezone(ZoneInfo(z)).utcoffset())
        return None, f"All offices  ·  {tz.slot_text(slot)} {tz.label(last)} update", []
    return None, "All offices", []


def run(*, week_label_: Optional[str] = None, tab: str = BOARD_TAB,
        dry_run: bool = False, show_all: bool = False, use_appstream: bool = True,
        refresh_index: bool = False, today: Optional[dt.date] = None,
        due: bool = False, zone: Optional[str] = None,
        now: Optional[dt.datetime] = None, logfn=print) -> dict:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(rep.CT)
    today = today or now.date()
    sh = fill.open_by_key(rep.SHEET_ID)
    tws, t_hrow, headers, widths, head_heights = _template(sh, logfn)
    width = len(headers)

    if week_label_:
        start = apst.week_start_for(week_label_)
    else:
        start = this_week_start(today)
    starts = [start, start - dt.timedelta(days=7)]

    all_weeks = src.parse_blocks(fill.worksheet_ci(sh, src.SOURCE_TAB).get_all_values())
    weeks, missing = [], []
    for s in starts:
        try:
            weeks.append(src.pick_week(all_weeks, week_label(s)))
            missing.append(None)
        except SystemExit:
            # The source tab has no block for this week yet (Monday morning, say):
            # show the week empty and say why, rather than failing the whole board.
            weeks.append(src.Week(label=week_label(s), header_row=0, owners=[]))
            missing.append(f"not on {src.SOURCE_TAB!r} yet")
    borrow_roster(weeks, missing)
    logfn(f"  this week {weeks[0].label} ({len(weeks[0].owners)} owners), "
          f"last week {weeks[1].label} ({len(weeks[1].owners)} owners)")

    roster = sorted({o.name for w in weeks for o in w.owners})
    no_zone = tz.unknown(roster)
    if no_zone:
        logfn(f"  {len(no_zone)} offices with no known time zone, run on the Central "
              f"clock: {', '.join(no_zone)}")
    in_pass, scope, _labels = pick_pass(roster, now, due=due, zone=zone)
    if in_pass is not None and not in_pass:
        logfn(f"  {now:%a %H:%M} CT: no office is at its 11:00 AM or 6:30 PM - nothing to do")
        return {"written": False, "due": 0, "notes": []}

    # Everybody else's numbers come from the last pass that pulled them. An
    # office the store has never seen is pulled now too, whatever its clock --
    # otherwise it would sit off the board until its own zone came round.
    stored, pulled_at = read_store(sh, headers)
    shown = {w.label for w in weeks}
    stored = {k: v for k, v in stored.items() if k[0] in shown}
    to_pull = None
    if in_pass is not None:
        seen = {k[2] for k in stored}
        to_pull = set(in_pass) | {o for o in roster if o not in seen}
        logfn(f"  pass: {scope} -> {len(in_pass)} offices"
              + (f" (+{len(to_pull) - len(in_pass)} never pulled before)"
                 if len(to_pull) > len(in_pass) else ""))
    fresh, notes = fetch_rows(weeks, starts, headers, today=today,
                              use_appstream=use_appstream, refresh_index=refresh_index,
                              only=to_pull, logfn=logfn)
    stamp = f"{now:%a} {now.month}/{now.day} {now:%H:%M}"
    rows = dict(stored)
    rows.update(fresh)
    pulled_at = {k: v for k, v in pulled_at.items() if k in rows}
    pulled_at.update({k: stamp for k in fresh})

    results = build_results(weeks, starts, headers, rows, today=today, show_all=show_all)
    for wr, why in zip(results, missing):
        wr.missing = why

    board_exists = True
    try:
        bws = fill.worksheet_ci(sh, tab)
        before = bws.get(f"A1:{ars.a1col(2 * width + GAP_COLS)}400",
                         value_render_option="UNFORMATTED_VALUE")
    except Exception:                                     # noqa: BLE001
        board_exists, before = False, []
    prior = read_prior(before, width, headers)
    moved = compare(results, prior, headers)

    what = ("every office" if show_all else
            f"offices at or under {rep.THRESHOLD:.0%} on 'Retention first showed up booked second'")
    status = (f"{what}  ·  every office re-checked at 11:00 AM and 6:30 PM Pacific  ·  "
              f"last pass: {scope}, checked {stamp} CT")
    if prior.stamp:
        status += (f"  ·  {len(moved)} moved since the {prior.stamp} check"
                   + (" (named on each day's band)" if moved else ""))
    layout = lay_out(results, headers, status, moved, show_all)

    for wr in results:
        for day, dr in wr.days.items():
            logfn(f"    {wr.label} {_band_text(dr, show_all)}")
    logfn(f"  {len(notes)} gaps" + "".join(f"\n    - {n}" for n in notes[:40]))
    if moved:
        logfn(f"  {len(moved)} moved since {prior.stamp}:")
        for (wk, day, owner), (_, note) in moved.items():
            logfn(f"    {wk} {day} {owner}: {note}")

    # The picture of this pass: only its offices (everybody, on a full run).
    pic_results = build_results(weeks, starts, headers, rows, today=today,
                                show_all=show_all, only=in_pass)
    for wr, why in zip(pic_results, missing):
        wr.missing = why
    pic_moved = {k: v for k, v in compare(pic_results, prior, headers).items()
                 if in_pass is None or k[2] in in_pass}
    picture = lay_out(pic_results, headers,
                      f"{scope}  ·  {what}  ·  checked {stamp} CT", pic_moved, show_all)

    if dry_run:
        logfn(f"  DRY RUN - nothing written ({layout.last_row} rows would be)")
        return {"written": False, "rows": layout.last_row, "moved": len(moved),
                "scope": scope, "notes": notes}

    _write_tab(sh, tab, tws, t_hrow, headers, widths, head_heights, layout,
               len(results), logfn)
    if use_appstream:
        # A run without AppStream has blank C/D/E; storing that would wipe the
        # real numbers of every office it pulled.
        write_store(sh, rows, pulled_at, headers)
    _write_tab(sh, PICTURE_TAB, tws, t_hrow, headers, widths, head_heights, picture,
               len(results), logfn)
    return {"written": True, "tab": tab, "picture_tab": PICTURE_TAB, "rows": layout.last_row,
            "moved": len(moved), "scope": scope, "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark.board")
    ap.add_argument("--week", default=None,
                    help="the week to show as THIS week, e.g. 9/13 (default: the current one)")
    ap.add_argument("--tab", default=BOARD_TAB)
    ap.add_argument("--all", dest="show_all", action="store_true",
                    help="list every office, not only those at or under the mark")
    ap.add_argument("--due", action="store_true",
                    help="pull only the offices whose local 11:00 AM / 6:30 PM it is now "
                         "(the scheduled passes)")
    ap.add_argument("--zone", default=None, choices=["Eastern", "Central", "Mountain", "Pacific"],
                    help="pull one time zone's offices by hand")
    ap.add_argument("--at", default=None,
                    help="pretend it is this CT time, 'YYYY-MM-DD HH:MM' (checking --due)")
    ap.add_argument("--no-appstream", dest="use_appstream", action="store_false")
    ap.add_argument("--refresh-index", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    now = (dt.datetime.strptime(args.at, "%Y-%m-%d %H:%M").replace(tzinfo=rep.CT)
           if args.at else None)
    res = run(week_label_=args.week, tab=args.tab, dry_run=args.dry_run,
              show_all=args.show_all, use_appstream=args.use_appstream,
              refresh_index=args.refresh_index, due=args.due, zone=args.zone, now=now)
    print(f"OK - { {k: v for k, v in res.items() if k != 'notes'} }")
    if res.get("due") == 0:
        return NOTHING_DUE
    return 0


# Exit code of a --due pass with no office at its 11:00 AM / 6:30 PM: the
# wrapper sends nothing and exits clean.
NOTHING_DUE = 3


if __name__ == "__main__":
    raise SystemExit(main())
