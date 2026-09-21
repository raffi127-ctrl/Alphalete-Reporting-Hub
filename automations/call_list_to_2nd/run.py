r"""Call List to 2nd Round -- the two-week board (Rafael, 2026-09-21).

Rafael's second report after '1st to 2nd Below the Mark': same idea (a board of
days, every office), different funnel stages. It lives on the 'Interviewers
Report from R to Z' workbook, on the tab Eve set up with the headers
('Sheet51' until the report gets its name).

    row 1   THIS WEEK (week of 9/20)          |   LAST WEEK (week of 9/13)
    row 2   status: where the numbers come from, when they were checked
    row 3   Eve's column headers              |   the same, again
            MONDAY 9/21                       |   MONDAY 9/14
            <every office with activity>      |   <every office with activity>
            TUESDAY 9/22 ...                  |   TUESDAY 9/15 ...

WHERE EACH COLUMN COMES FROM (found by header text, never by position)
    Owner Name            'Interviewers Retention (Interviewer)' roster,
                          ARS Management 2.0 (the same owners as Below the Mark)
    Interviewer Name      the owner's ARS REPORT tab, col '1st Round Interviewer'
                          of the rows dated that day (1st or 2nd round)
    Sent to call list     \
    Retention Call list    \  ApplicantStream -> Reports -> Retention Details,
    1st rds booked          > per office, that day's column:
    1st rds showed         /  'Sent to Call List', 'Retention Call List',
    1st rd %              /   'Total First Interviews', 'First Interviews
                              Showed Up', 'Retention First Interviews'
    2nd interviews booked \   the owner's ARS REPORT tab (the interviewer's
    2nd interviews showed  >  report, Camila's Drive): rows whose 'Date 2nd Rd'
    2nd interview %       /   is that day -- see count_second_rounds

Rafael: "for second rounds booked ... you're gonna have to pull from the
interviewer's report, because it's gonna go based off the interviewer's name".

EVERY DAY IS RE-CHECKED ON EVERY RUN: owners forget to mark 'Showed' and fill it
in days later, so each run re-reads both weeks from scratch.

COLOURS (Rafael, 2026-09-21), whole column, both weeks:
    Retention Call list, 1st rd %   >= 50% green  |  45%-49.99% grey  |  < 45% red
    2nd interview %                 >= 50% green  |  < 50% red  (no grey)

WHEN: 1:00 PM LOCAL per office (--due picks the offices whose local 1 PM it is;
offices not in the pass keep the numbers the board already shows).

Run:
    python -m automations.call_list_to_2nd.run --dry-run
    python -m automations.call_list_to_2nd.run                 # writes the SANDBOX tab
    python -m automations.call_list_to_2nd.run --no-appstream  # 2nd-round side only
    python -m automations.call_list_to_2nd.run --due           # the scheduled 1 PM passes
    python -m automations.call_list_to_2nd.run --production    # the real tab
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:                                   # accents are safe on the Windows console
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill

SHEET_ID = "1amAXf1rguSMvQ3HRNiCpJC8pgTlTPT5503S0Yns3IA4"   # Interviewers Report from R to Z
PRODUCTION_TAB = "Call List to 2nd Round"          # Eve's tab (was 'Sheet51')
SANDBOX_TAB = "Call List to 2nd Round SANDBOX"    # a copy of it; the default target

CT = ZoneInfo("America/Chicago")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]   # Rafael: Mon-Fri
RUN_AT = (13, 0)                       # 1:00 PM local (Rafael)
LATE_OK_MIN = 45

TITLE_ROW, STATUS_ROW, HEADER_ROW = 1, 2, 3
FIRST_BODY_ROW = 4
GAP_COLS = 1
TITLE = "CALL LIST TO 2ND ROUND"

# field key -> the header text on Eve's tab (matched loosely: case/spaces).
HEADERS = {
    "owner": "Owner Name",
    "interviewer": "Interviewer Name",
    "sent": "Sent to call list",
    "call_ret": "Retention Call list",
    "b1": "1st rds booked",
    "s1": "1st rds showed",
    "r1": "1st rd %",
    "b2": "2nd interviews booked",
    "s2": "2nd interviews showed",
    "r2": "2nd interview %",
}
PCT_FIELDS = ("call_ret", "r1", "r2")
# Rafael (2026-09-21): "1st rds booked / showed should be per owner, but if
# there's multiple interviewers then there should be 2 rows." So an office is a
# GROUP of rows, one per interviewer: the owner's columns (AppStream is per
# office) are merged down the group, the 2nd-round columns are per interviewer.
OWNER_FIELDS = ("owner", "sent", "call_ret", "b1", "s1", "r1")
INTERVIEWER_FIELDS = ("interviewer", "b2", "s2", "r2")
COUNT_FIELDS = ("sent", "b1", "s1", "b2", "s2")

# AppStream Retention Details row label -> field. Percents arrive as 44 for 44%.
AS_ROWS = {
    "sent": "sent_to_call_list",
    "call_ret": "pct_apps_booked_first",
    "b1": "first_booked",
    "s1": "first_showed",
    "r1": "pct_first_retention",
}
AS_PERCENT = {"call_ret", "r1"}

# ARS REPORT log columns, by header text.
LOG_DATE1 = "date 1st rd"
LOG_INTERVIEWER = "1st round interviewer"
LOG_BOOKED = "booked to 2nd rd"
LOG_DATE2 = "date 2nd rd"
LOG_SHOWED = "showed up to 2nd round"

# Colour bands: (field, [(lo, hi, colour)]) -- lo inclusive, hi exclusive.
GREEN = {"red": 0.576, "green": 0.769, "blue": 0.490}     # #93C47D
GREY = {"red": 0.800, "green": 0.800, "blue": 0.800}      # #CCCCCC
RED = {"red": 0.918, "green": 0.263, "blue": 0.208}       # #EA4335, as Below the Mark
BANDS = {
    "call_ret": [(None, 0.45, RED), (0.45, 0.50, GREY), (0.50, None, GREEN)],
    "r1": [(None, 0.45, RED), (0.45, 0.50, GREY), (0.50, None, GREEN)],
    "r2": [(None, 0.50, RED), (0.50, None, GREEN)],
}
BAND_NOTES = {
    "call_ret": "50%+ green · 45%-49.99% grey · under 45% red (Rafael)",
    "r1": "50%+ green · 45%-49.99% grey · under 45% red (Rafael)",
    "r2": "50%+ green · under 50% red, no grey (Rafael)",
}

NAME_WIDTHS = {"owner": 150, "interviewer": 230}

DAY_BG = {"red": 0.263, "green": 0.263, "blue": 0.263}
WEEK_BG = {"red": 0.4, "green": 0.4, "blue": 0.4}
STATUS_BG = {"red": 0.937, "green": 0.937, "blue": 0.937}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


# ------------------------------------------------------------------ the dates
def week_start(d: dt.date) -> dt.date:
    """The Sunday that starts d's week -- how AppStream names a week."""
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def this_week_start(today: dt.date) -> dt.date:
    """On a Sunday the new week has no day in it yet: keep the one that ended."""
    if today.weekday() == 6:
        today -= dt.timedelta(days=1)
    return week_start(today)


def day_date(start: dt.date, day: str) -> dt.date:
    return start + dt.timedelta(days=DAYS.index(day) + 1)


def md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


_DATE_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?")


def parse_date(raw, year_hint: int) -> Optional[dt.date]:
    """'9/21/2026' / '9/21/26' / '9/21' -> date; anything else -> None."""
    m = _DATE_RE.match(str(raw or ""))
    if not m:
        return None
    y = m.group(3)
    year = year_hint if not y else (int(y) + 2000 if len(y) == 2 else int(y))
    try:
        return dt.date(year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


# ------------------------------------------------------------- column lookup
def _hkey(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace(" ", " ")).strip().lower()


def resolve_columns(header_row: List[str]) -> List[str]:
    """Field key for each header cell of Eve's row, in the tab's own order.
    Raises when a header Rafael asked for is missing -- the board would
    otherwise quietly shift numbers under the wrong heading."""
    want = {_hkey(v): k for k, v in HEADERS.items()}
    order: List[str] = []
    for cell in header_row:
        k = want.get(_hkey(cell))
        # Eve's block ends at the first blank cell, or where last week's copy
        # of it starts -- only the left block defines the columns.
        if not _hkey(cell) or (k and k in order):
            break
        if k:
            order.append(k)
        elif _hkey(cell):
            order.append("")                               # a column we do not own
    while order and not order[-1]:
        order.pop()
    missing = [HEADERS[k] for k in HEADERS if k not in order]
    if missing:
        raise SystemExit(f"header row is missing: {', '.join(missing)}")
    return order


# ------------------------------------------------ 2nd rounds, from the ARS log
@dataclass
class LogCols:
    date1: int
    interviewer: int
    booked: int
    date2: int
    showed: int


def log_columns(header: List[str]) -> Optional[LogCols]:
    h = [_hkey(x) for x in header]
    try:
        return LogCols(h.index(LOG_DATE1), h.index(LOG_INTERVIEWER), h.index(LOG_BOOKED),
                       h.index(LOG_DATE2), h.index(LOG_SHOWED))
    except ValueError:
        return None


# 'Showed Up to 2nd Round' values that take a row OUT of that day's 2nd rounds:
# a reschedule did not happen that day, a pause is on hold.
NOT_THAT_DAY = {"reschedule requested", "paused"}
ATTENDED = {"showed"}


NO_INTERVIEWER = "(no interviewer)"


@dataclass
class SecondRounds:
    booked: int = 0
    showed: int = 0
    interviewers: List[str] = field(default_factory=list)       # everyone active that day
    by: Dict[str, List[int]] = field(default_factory=dict)      # interviewer -> [booked, showed]


def count_second_rounds(values: List[List[str]], year: int) -> Dict[dt.date, SecondRounds]:
    """{date: SecondRounds} out of one owner's ARS REPORT log.

    A 2nd round counts on its 'Date 2nd Rd' when 'Booked to 2nd Rd' is Booked
    (or the outcome was already filled in), unless it was rescheduled / paused.
    It counts as showed only on 'Showed'; a blank outcome on a past day is an
    owner who did not update -- that is exactly what this board is meant to
    surface, so it stays in the denominator.

    Each 2nd round is credited to the row's '1st Round Interviewer' (`by`);
    `interviewers` names everyone with a row dated that day, 1st or 2nd round."""
    if not values:
        return {}
    cols = log_columns(values[0])
    if cols is None:
        raise LookupError("log headers not found (Date 1st Rd / Booked to 2nd Rd / ...)")
    out: Dict[dt.date, SecondRounds] = {}
    names: Dict[dt.date, Dict[str, int]] = {}

    def cell(r, i):
        return str(r[i]).strip() if i < len(r) else ""

    for r in values[1:]:
        who = cell(r, cols.interviewer)
        d1 = parse_date(cell(r, cols.date1), year)
        d2 = parse_date(cell(r, cols.date2), year)
        booked = cell(r, cols.booked).lower()
        outcome = cell(r, cols.showed).lower()
        if d1 and who:
            names.setdefault(d1, {}).setdefault(who, 0)
            names[d1][who] += 1
        if not d2 or outcome in NOT_THAT_DAY:
            continue
        if booked != "booked" and not outcome:
            continue
        sr = out.setdefault(d2, SecondRounds())
        mine = sr.by.setdefault(who or NO_INTERVIEWER, [0, 0])
        sr.booked += 1
        mine[0] += 1
        if outcome in ATTENDED:
            sr.showed += 1
            mine[1] += 1
        if who:
            names.setdefault(d2, {}).setdefault(who, 0)
            names[d2][who] += 1
    for d, counts in names.items():
        out.setdefault(d, SecondRounds()).interviewers = sorted(
            counts, key=lambda n: (-counts[n], n.lower()))
    return out


def read_logs(owners: List[str], year: int, *, refresh_index: bool = False,
              logfn=print) -> Tuple[Dict[str, Dict[dt.date, SecondRounds]], List[str]]:
    """Every owner's log, one batch read per ARS REPORT workbook."""
    from automations.first_to_second_below_mark import ars_reports as ars

    index = ars._index(logfn=logfn, refresh=refresh_index)
    aliases = ars.load_aliases()
    notes: List[str] = []
    by_book: Dict[str, List[Tuple[str, str]]] = {}
    for owner in owners:
        hit = ars.find_tab(owner, index, aliases)
        if hit is None:
            notes.append(f"{owner}: no ARS REPORT tab")
            continue
        by_book.setdefault(hit[0], []).append((owner, hit[1]))

    out: Dict[str, Dict[dt.date, SecondRounds]] = {}
    for book, pairs in by_book.items():
        sh = fill.open_by_key(ars.ARS_WORKBOOKS[book])
        res = sh.values_batch_get([f"'{tab}'!A1:K" for _, tab in pairs])
        for (owner, tab), vr in zip(pairs, res.get("valueRanges", [])):
            try:
                out[owner] = count_second_rounds(vr.get("values", []), year)
            except LookupError as exc:
                notes.append(f"{owner} ({book} / {tab}): {exc}")
    logfn(f"  ARS REPORT: {len(out)} of {len(owners)} owners read")
    return out, notes


# ------------------------------------------------ 1st rounds, from AppStream
def fetch_appstream(owners: List[str], starts: List[dt.date], *, logfn=print
                    ) -> Tuple[Dict[Tuple[str, dt.date], Dict[str, Optional[float]]], List[str]]:
    """{(owner, date): {field: value}} for every day of the given weeks.

    One office switch per owner, one week submit per week -- the same sweep
    Below the Mark runs, with the funnel's front-half rows instead."""
    from automations.recruiting_report import fetch_office
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.first_to_second_below_mark import appstream as apst

    index = apst.build_office_index()
    notes: List[str] = []
    targets = []
    for owner in owners:
        hit = apst.resolve_office(owner, index)
        if hit is None:
            notes.append(f"{owner}: no AppStream office id")
        else:
            targets.append((owner, hit[0], hit[1]))
    logfn(f"  AppStream: {len(targets)} offices, weeks "
          + ", ".join(md(s) for s in starts))

    out: Dict[Tuple[str, dt.date], Dict[str, Optional[float]]] = {}
    with appstream_direct_session(verbose=False) as page:
        for owner, office_id, hint in targets:
            try:
                if not fetch_office._switch_office(page, office_id, hint, confirm_denial=True):
                    notes.append(f"{owner} (office {office_id}): no AppStream access")
                    continue
                fetch_office._ensure_on_retention_report(page)
            except Exception as exc:                          # noqa: BLE001
                notes.append(f"{owner} (office {office_id}): {type(exc).__name__}: {exc}")
                continue
            for start in starts:
                try:
                    fetch_office._set_week_and_submit(page, start)
                    page.wait_for_timeout(500)
                    raw = fetch_office._scrape_metrics_per_day(page)
                except Exception as exc:                      # noqa: BLE001
                    notes.append(f"{owner} (office {office_id}, week {md(start)}): "
                                 f"{type(exc).__name__}: {exc}")
                    continue
                for day in DAYS:
                    row: Dict[str, Optional[float]] = {}
                    for f, metric in AS_ROWS.items():
                        v = (raw.get(metric) or {}).get(day.lower())
                        row[f] = None if v is None else (v / 100.0 if f in AS_PERCENT else v)
                    out[(owner, day_date(start, day))] = row
            logfn(f"    {owner}: ok")
    return out, notes


# ------------------------------------------------------------- assembling rows
def ratio(num, den) -> Optional[float]:
    if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den:
        return num / den
    return None


def make_group(owner: str, fallback_interviewers: List[str], as_row: Optional[dict],
               sr: Optional[SecondRounds], *, is_today: bool = False) -> Optional[List[dict]]:
    """One office's rows for one day -- one per interviewer with 2nd rounds that
    day, most booked first -- or None when nothing happened. The FIRST row
    carries the owner's AppStream numbers; they are merged down the group.

    TODAY's 2nd-round % is left blank: at 1 PM most of the day's 2nd rounds
    have not happened yet, and a column of reds would be noise. The counts
    still show; the % fills in on the next day's run."""
    as_row = as_row or {}
    head = {"owner": owner}
    for f in AS_ROWS:
        head[f] = as_row.get(f)
    # AppStream's own 1st-round % is used as-is; if it is missing but the two
    # counts are there, the % is worked out so the row still reads.
    if head.get("r1") is None:
        head["r1"] = ratio(head.get("s1"), head.get("b1"))

    def pct(showed, booked):
        return None if is_today else ratio(showed, booked)

    rows: List[dict] = []
    if sr and sr.by:
        for name, (b, sh) in sorted(sr.by.items(), key=lambda kv: (-kv[1][0], kv[0].lower())):
            rows.append({"owner": owner, "interviewer": name, "b2": b, "s2": sh, "r2": pct(sh, b)})
    else:
        names = sr.interviewers if sr and sr.interviewers else fallback_interviewers
        rows.append({"owner": owner, "interviewer": ", ".join(names), "b2": 0, "s2": 0, "r2": None})
    rows[0].update(head)
    active = any(isinstance(r.get(f), (int, float)) and r[f] for r in rows for f in COUNT_FIELDS)
    return rows if active else None


# ----------------------------------------------------------------- the layout
@dataclass
class Band:
    row: int              # 1-indexed
    side: int             # 0 = this week (left), 1 = last week (right)
    text: str


@dataclass
class Layout:
    width: int
    values: List[List] = field(default_factory=list)   # rows from FIRST_BODY_ROW
    bands: List[Band] = field(default_factory=list)
    data_rows: List[Tuple[int, int]] = field(default_factory=list)   # (row, side)
    groups: List[Tuple[int, int, int]] = field(default_factory=list)  # (first row, rows, side)

    @property
    def last_row(self) -> int:
        return FIRST_BODY_ROW + len(self.values) - 1


# ------------------------------------------------------- what moved since last run
# Rafael: owners forget to update and fill in past days later, so every run
# re-checks both weeks -- and says which numbers MOVED since the last check.
# It goes on the day's band, never in a cell note: notes print at the foot of
# an exported picture (the Below the Mark lesson).
CHANGE_LABEL = {"call_ret": "Call list %", "r1": "1st %", "r2": "2nd %"}
BAND_MAX_CHANGES = 4
_STAMP_RE = re.compile(r"last checked (\w{3} \d{1,2}/\d{1,2} \d{1,2}:\d{2} CT)")


@dataclass
class Change:
    owner: str
    date: dt.date
    key: str
    old: float
    new: float
    interviewer: str = ""

    @property
    def text(self) -> str:
        who = f"{self.owner} ({self.interviewer})" if self.interviewer else self.owner
        return f"{who} {CHANGE_LABEL[self.key]} {self.old:.0%}→{self.new:.0%}"


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def compare(prev: Dict[Tuple[str, dt.date], List[dict]],
            weeks: List[Tuple[dt.date, Dict[str, List[List[dict]]]]]) -> Dict[dt.date, List[Change]]:
    """{date: [Change]} -- a % that was a number last run and is a different
    number now. The owner's %s compare office to office, the 2nd % interviewer
    to interviewer. A % showing up for the first time (today's 2nd % filling
    in the next day) is not a change. Biggest moves first."""
    out: Dict[dt.date, List[Change]] = {}

    def moved(old, new) -> bool:
        return old is not None and new is not None and round(old, 3) != round(new, 3)

    for start, days in weeks:
        for day, groups in days.items():
            d = day_date(start, day)
            for group in groups:
                owner = group[0]["owner"]
                before = prev.get((owner, d))
                if not before:
                    continue
                for key in ("call_ret", "r1"):
                    old, new = _num(before[0].get(key)), _num(group[0].get(key))
                    if moved(old, new):
                        out.setdefault(d, []).append(Change(owner, d, key, old, new))
                was = {r.get("interviewer"): r for r in before}
                for rec in group:
                    old_rec = was.get(rec.get("interviewer"))
                    if not old_rec:
                        continue
                    old, new = _num(old_rec.get("r2")), _num(rec.get("r2"))
                    if moved(old, new):
                        # One interviewer per office needs no name in brackets.
                        who = rec["interviewer"] if len(group) > 1 else ""
                        out.setdefault(d, []).append(Change(owner, d, "r2", old, new, who))
    for lst in out.values():
        lst.sort(key=lambda c: -abs(c.new - c.old))
    return out


def prior_stamp(values: List[List]) -> Optional[str]:
    for row in values[:STATUS_ROW]:
        for cell in row:
            m = _STAMP_RE.search(str(cell))
            if m:
                return m.group(1)
    return None


def day_band_text(day: str, d: dt.date, today: dt.date, n: int,
                  changes: Optional[List[Change]] = None) -> str:
    text = f"{day.upper()} {md(d)}"
    if d > today:
        return text + "  ·  not yet"
    if d == today:
        text += "  ·  today: 2nd-round % fills in tomorrow"
    text += f"  ·  {n} office{'s' if n != 1 else ''}" if n else "  ·  no activity"
    if changes:
        shown = ", ".join(c.text for c in changes[:BAND_MAX_CHANGES])
        more = len(changes) - BAND_MAX_CHANGES
        text += f"  ·  CHANGED: {shown}" + (f" (+{more} more)" if more > 0 else "")
    return text


def lay_out(order: List[str], weeks: List[Tuple[dt.date, Dict[str, List[List[dict]]]]],
            today: dt.date, changes: Optional[Dict[dt.date, List["Change"]]] = None) -> Layout:
    """Both weeks side by side, each day starting on the same row on both sides.
    An office is a group of rows (one per interviewer); the owner's columns are
    written on the group's first row only, to be merged down it."""
    width = len(order)
    lay = Layout(width=width)
    total = 2 * width + GAP_COLS
    r = FIRST_BODY_ROW
    for day in DAYS:
        blocks = []
        for side, (start, days) in enumerate(weeks):
            d = day_date(start, day)
            groups = days.get(day, []) if d <= today else []
            blocks.append((side, d, groups))
        height = 1 + max(sum(len(g) for g in groups) for _, _, groups in blocks)
        grid = [[""] * total for _ in range(height)]
        for side, d, groups in blocks:
            c0 = side * (width + GAP_COLS)
            text = day_band_text(day, d, today, len(groups), (changes or {}).get(d))
            grid[0][c0] = text
            lay.bands.append(Band(row=r, side=side, text=text))
            i = 1
            for group in groups:
                lay.groups.append((r + i, len(group), side))
                for n, rec in enumerate(group):
                    for j, key in enumerate(order):
                        if not key or (n and key in OWNER_FIELDS):
                            continue
                        v = rec.get(key)
                        grid[i][c0 + j] = "" if v is None else v
                    lay.data_rows.append((r + i, side))
                    i += 1
        lay.values.extend(grid)
        r += height
    return lay


# ---------------------------------------------------------- reading back a pass
_BAND_RE = re.compile(r"^(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY)\s+(\d{1,2})/(\d{1,2})")


def read_back(values: List[List], order: List[str], year: int
              ) -> Dict[Tuple[str, dt.date], List[dict]]:
    """{(owner, date): [rows]} off the board as it stands, so a --due pass that
    pulls only some offices keeps everybody else's numbers. A merged owner cell
    reads blank below its first row: a row with no owner but an interviewer
    belongs to the office above it."""
    width = len(order)
    oi = order.index("owner")
    ii = order.index("interviewer")
    out: Dict[Tuple[str, dt.date], List[dict]] = {}
    for side in (0, 1):
        c0 = side * (width + GAP_COLS)
        cur: Optional[dt.date] = None
        owner = ""
        for row in values[FIRST_BODY_ROW - 1:]:
            cells = list(row[c0:c0 + width]) + [""] * width
            first = str(cells[0] or "").strip()
            m = _BAND_RE.match(first)
            if m:
                cur, owner = dt.date(year, int(m.group(2)), int(m.group(3))), ""
                continue
            name = str(cells[oi] or "").strip()
            if cur is None or not (name or (owner and str(cells[ii] or "").strip())):
                owner = ""
                continue
            rec = {k: (cells[j] if cells[j] != "" else None)
                   for j, k in enumerate(order) if k and (name or k in INTERVIEWER_FIELDS)}
            if name:
                owner = name
                out[(owner, cur)] = [rec]
            else:
                rec["owner"] = owner
                out[(owner, cur)].append(rec)
    return out


# --------------------------------------------------------------- writing
def _rng(sid, r0, r1, c0, c1):
    """0-indexed, end-exclusive GridRange."""
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _band_rule(sid, ranges, lo, hi, colour, col_letter, first_row):
    cell = f"{col_letter}{first_row}"
    parts = [f"ISNUMBER({cell})"]
    if lo is not None:
        parts.append(f"{cell}>={lo}")
    if hi is not None:
        parts.append(f"{cell}<{hi}")
    fg = WHITE if colour is RED else {"red": 0, "green": 0, "blue": 0}
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": ranges,
        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                      "values": [{"userEnteredValue": f"=AND({','.join(parts)})"}]},
                        "format": {"backgroundColor": colour,
                                   "textFormat": {"foregroundColor": fg, "bold": colour is RED}}}}}}


def _a1col(n: int) -> str:
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def ensure_tab(sh, tab: str, logfn=print):
    """The target tab, created as a copy of Eve's tab for the sandbox."""
    try:
        return fill.worksheet_ci(sh, tab)
    except Exception:                                     # noqa: BLE001
        if tab != SANDBOX_TAB:
            raise
        src = fill.worksheet_ci(sh, PRODUCTION_TAB)
        logfn(f"  creating {tab!r} as a copy of {PRODUCTION_TAB!r}")
        return sh.duplicate_sheet(src.id, new_sheet_name=tab)


def ensure_top_rows(ws, logfn=print) -> List[str]:
    """Make room for the title + status rows ABOVE Eve's header -- inserted,
    never written over -- and return her header row."""
    top = ws.get("A1:Z3")
    first = [str(x) for x in (top[0] if top else [])]
    if any(_hkey(x) == _hkey(HEADERS["owner"]) for x in first):
        logfn("  inserting the title + status rows above the header")
        ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS", "startIndex": 0, "endIndex": 2},
            "inheritFromBefore": False}}]})
        return first
    return [str(x) for x in (top[HEADER_ROW - 1] if len(top) >= HEADER_ROW else [])]


def write(ws, order: List[str], lay: Layout, titles: List[str], status: str, logfn=print):
    sh = ws.spreadsheet
    sid = ws.id
    width = len(order)
    total = 2 * width + GAP_COLS
    last = max(lay.last_row, FIRST_BODY_ROW)
    need_rows = last + 5
    if ws.row_count < need_rows or ws.col_count < total:
        ws.resize(rows=max(ws.row_count, need_rows), cols=max(ws.col_count, total))

    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,conditionalFormats,merges)"})
    mine = next(s for s in meta["sheets"] if s["properties"]["sheetId"] == sid)
    reqs: List[dict] = []
    # This tab is generated below the header: drop old rules and merges there.
    for _ in mine.get("conditionalFormats", []):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    for m in mine.get("merges", []):
        if m.get("startRowIndex", 0) != HEADER_ROW - 1:
            reqs.append({"unmergeCells": {"range": m}})
    body_end = max(ws.row_count, need_rows)
    reqs.append({"updateCells": {"range": _rng(sid, FIRST_BODY_ROW - 1, body_end, 0, total),
                                 "fields": "userEnteredValue,userEnteredFormat,note"}})
    reqs.append({"updateCells": {"range": _rng(sid, 0, 2, 0, total),
                                 "fields": "userEnteredValue,userEnteredFormat"}})
    # Last week's header: a copy of Eve's, look and all.
    reqs.append({"copyPaste": {"source": _rng(sid, HEADER_ROW - 1, HEADER_ROW, 0, width),
                               "destination": _rng(sid, HEADER_ROW - 1, HEADER_ROW,
                                                   width + GAP_COLS, total),
                               "pasteType": "PASTE_NORMAL"}})
    for side in (0, 1):
        c0 = side * (width + GAP_COLS)
        for r0, bg, size in ((TITLE_ROW - 1, WEEK_BG, 12), (STATUS_ROW - 1, STATUS_BG, 9)):
            reqs.append({"mergeCells": {"range": _rng(sid, r0, r0 + 1, c0, c0 + width),
                                        "mergeType": "MERGE_ALL"}})
            reqs.append({"repeatCell": {"range": _rng(sid, r0, r0 + 1, c0, c0 + width),
                "cell": {"userEnteredFormat": {
                    "backgroundColor": bg, "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                    "textFormat": {"bold": r0 == TITLE_ROW - 1, "fontSize": size,
                                   "foregroundColor": WHITE if bg is WEEK_BG else
                                   {"red": 0.2, "green": 0.2, "blue": 0.2}}}},
                "fields": "userEnteredFormat"}})
        # The colour rule written on the header cell, so it is never a guess.
        for j, key in enumerate(order):
            if key in BAND_NOTES:
                reqs.append({"updateCells": {
                    "range": _rng(sid, HEADER_ROW - 1, HEADER_ROW, c0 + j, c0 + j + 1),
                    "rows": [{"values": [{"note": BAND_NOTES[key]}]}], "fields": "note"}})
    # Body: numbers centred, percents as percents, a light grid.
    body = _rng(sid, FIRST_BODY_ROW - 1, last, 0, total)
    reqs.append({"repeatCell": {"range": body, "cell": {"userEnteredFormat": {
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
        "textFormat": {"fontSize": 10}}}, "fields": "userEnteredFormat"}})
    for side in (0, 1):
        c0 = side * (width + GAP_COLS)
        for j, key in enumerate(order):
            if key in ("owner", "interviewer"):
                reqs.append({"repeatCell": {"range": _rng(sid, FIRST_BODY_ROW - 1, last, c0 + j, c0 + j + 1),
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
                    "fields": "userEnteredFormat.horizontalAlignment"}})
            if key in PCT_FIELDS:
                reqs.append({"repeatCell": {"range": _rng(sid, FIRST_BODY_ROW - 1, last, c0 + j, c0 + j + 1),
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                    "fields": "userEnteredFormat.numberFormat"}})
    for row, side in lay.data_rows:
        c0 = side * (width + GAP_COLS)
        reqs.append({"updateBorders": {"range": _rng(sid, row - 1, row, c0, c0 + width),
            **{k: {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.8}}
               for k in ("top", "bottom", "left", "right", "innerVertical")}}})
    for first, rows, side in lay.groups:
        c0 = side * (width + GAP_COLS)
        if rows > 1:
            for j, key in enumerate(order):
                if key in OWNER_FIELDS:
                    reqs.append({"mergeCells": {"range": _rng(sid, first - 1, first - 1 + rows,
                                                              c0 + j, c0 + j + 1),
                                                "mergeType": "MERGE_ALL"}})
        # A darker line between offices, so a group reads as one office.
        reqs.append({"updateBorders": {"range": _rng(sid, first - 1, first, c0, c0 + width),
            "top": {"style": "SOLID_MEDIUM", "color": {"red": 0.5, "green": 0.5, "blue": 0.5}}}})
    for b in lay.bands:
        c0 = b.side * (width + GAP_COLS)
        rng = _rng(sid, b.row - 1, b.row, c0, c0 + width)
        reqs.append({"mergeCells": {"range": rng, "mergeType": "MERGE_ALL"}})
        reqs.append({"repeatCell": {"range": rng, "cell": {"userEnteredFormat": {
            "backgroundColor": DAY_BG, "horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE}}},
            "fields": "userEnteredFormat"}})
        reqs.append({"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "ROWS", "startIndex": b.row - 1, "endIndex": b.row},
            "properties": {"pixelSize": 28}, "fields": "pixelSize"}})
    # Colours: the whole column, both weeks.
    for key, bands in BANDS.items():
        j = order.index(key)
        ranges = [_rng(sid, FIRST_BODY_ROW - 1, last, s * (width + GAP_COLS) + j,
                       s * (width + GAP_COLS) + j + 1) for s in (0, 1)]
        letter = _a1col(j + 1)
        for lo, hi, colour in bands:
            reqs.append(_band_rule(sid, ranges, lo, hi, colour, letter, FIRST_BODY_ROW))
    reqs.append({"updateDimensionProperties": {"range": {
        "sheetId": sid, "dimension": "COLUMNS", "startIndex": width, "endIndex": width + GAP_COLS},
        "properties": {"pixelSize": 24}, "fields": "pixelSize"}})
    # Names have to read whole: the owner and interviewer columns are widened.
    for side in (0, 1):
        c0 = side * (width + GAP_COLS)
        for key, px in NAME_WIDTHS.items():
            j = order.index(key)
            reqs.append({"updateDimensionProperties": {"range": {
                "sheetId": sid, "dimension": "COLUMNS", "startIndex": c0 + j, "endIndex": c0 + j + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    sh.batch_update({"requests": reqs})

    top = [[""] * total, [""] * total]
    for side in (0, 1):
        c0 = side * (width + GAP_COLS)
        top[0][c0] = titles[side]
        top[1][c0] = status
    ws.update(values=top, range_name=f"A1:{_a1col(total)}2", value_input_option="RAW")
    if lay.values:
        ws.update(values=lay.values,
                  range_name=f"A{FIRST_BODY_ROW}:{_a1col(total)}{lay.last_row}",
                  value_input_option="RAW")
    logfn(f"  wrote {len(lay.values)} rows to {ws.title!r}")


# ----------------------------------------------------------------- the pass
def due_now(owners: List[str], now: dt.datetime) -> List[str]:
    """Owners whose local 1:00 PM it is right now (unknown zones run on Central)."""
    from automations.first_to_second_below_mark import office_tz as tz
    picked = []
    for o in owners:
        z, _ = tz.zone_or_fallback(o)
        local = now.astimezone(ZoneInfo(z))
        start = local.replace(hour=RUN_AT[0], minute=RUN_AT[1], second=0, microsecond=0)
        if dt.timedelta(0) <= local - start <= dt.timedelta(minutes=LATE_OK_MIN):
            picked.append(o)
    return picked


def load_roster(starts: List[dt.date], logfn=print) -> Dict[str, List[str]]:
    """{owner: [interviewers]} -- the owners on 'Interviewers Retention
    (Interviewer)' for either week, the same list Below the Mark reports on."""
    from automations.first_to_second_below_mark import run as rep
    from automations.first_to_second_below_mark import source as src
    sh = fill.open_by_key(rep.SHEET_ID)
    blocks = src.parse_blocks(fill.worksheet_ci(sh, src.SOURCE_TAB).get_all_values())
    roster: Dict[str, List[str]] = {}
    for s in starts:
        try:
            wk = src.pick_week(blocks, md(s))
        except (SystemExit, RuntimeError):
            logfn(f"  week {md(s)} not on {src.SOURCE_TAB!r} yet")
            continue
        for o in wk.owners:
            roster.setdefault(o.name, list(o.interviewers))
    return roster


def run(*, tab: str = SANDBOX_TAB, dry_run: bool = False, use_appstream: bool = True,
        due: bool = False, now: Optional[dt.datetime] = None, only: Optional[List[str]] = None,
        refresh_index: bool = False, logfn=print) -> dict:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(CT)
    today = now.date()
    start = this_week_start(today)
    starts = [start, start - dt.timedelta(days=7)]

    roster = load_roster(starts, logfn)
    owners = sorted(roster, key=str.lower)
    if only:
        want = {o.lower() for o in only}
        owners = [o for o in owners if o.lower() in want]
    logfn(f"  {len(owners)} owners, this week {md(starts[0])}, last week {md(starts[1])}")

    to_pull = owners
    if due:
        to_pull = due_now(owners, now)
        if not to_pull:
            logfn(f"  {now:%a %H:%M} CT: no office is at its 1:00 PM - nothing to do")
            return {"written": False, "due": 0}
        logfn(f"  1 PM pass: {len(to_pull)} offices")

    sh = fill.open_by_key(SHEET_ID)
    ws = ensure_tab(sh, tab, logfn) if not dry_run else None
    if ws is not None:
        header = ensure_top_rows(ws, logfn)
    else:
        try:
            probe = fill.worksheet_ci(sh, tab)
        except Exception:                                 # noqa: BLE001
            probe = fill.worksheet_ci(sh, PRODUCTION_TAB)
        top = probe.get("A1:Z3")
        header = next((list(map(str, r)) for r in top
                       if any(_hkey(x) == _hkey(HEADERS["owner"]) for x in r)), [])
    order = resolve_columns(header)

    logs, notes = read_logs(to_pull, start.year, refresh_index=refresh_index, logfn=logfn)
    as_data: Dict[Tuple[str, dt.date], dict] = {}
    if use_appstream and to_pull:
        try:
            as_data, gaps = fetch_appstream(to_pull, starts, logfn=logfn)
            notes.extend(gaps)
        except Exception as exc:                          # noqa: BLE001
            notes.append(f"AppStream unavailable: {type(exc).__name__}: {exc}")
            logfn(f"  !! AppStream unavailable ({type(exc).__name__}: {exc})")

    # The board as it stands: the "before" for what moved, and the numbers of
    # the offices a --due pass does not pull.
    board = ws if ws is not None else next(
        (w for w in sh.worksheets() if w.title.strip().lower() == tab.strip().lower()), None)
    before = board.get_all_values(value_render_option="UNFORMATTED_VALUE") if board else []
    prev = read_back(before, order, start.year) if before else {}
    prev_stamp = prior_stamp(before)
    kept = prev if set(to_pull) != set(owners) else {}

    weeks = []
    for s in starts:
        days: Dict[str, List[List[dict]]] = {}
        for day in DAYS:
            d = day_date(s, day)
            groups = []
            for o in owners:
                if o in to_pull:
                    group = make_group(o, roster.get(o, []), as_data.get((o, d)),
                                       (logs.get(o) or {}).get(d), is_today=d == today)
                else:
                    group = kept.get((o, d))
                if group:
                    groups.append(group)
            days[day] = groups
        weeks.append((s, days))
    changes = compare(prev, weeks) if prev_stamp else {}
    lay = lay_out(order, weeks, today, changes)

    for s, days in weeks:
        for day in DAYS:
            if day_date(s, day) <= today:
                logfn(f"    {md(s)} {day[:3]}: {len(days[day])} offices")
    logfn(f"  {len(notes)} gaps" + "".join(f"\n    - {n}" for n in notes[:60]))
    moved = [c for d in sorted(changes) for c in changes[d]]
    if moved:
        logfn(f"  {len(moved)} changed since {prev_stamp}:")
        for c in moved:
            logfn(f"    {c.date:%a} {md(c.date)} {c.text}")

    stamp = f"{now:%a} {now.month}/{now.day} {now:%H:%M} CT"
    status = ("1st round: ApplicantStream  ·  2nd round: each owner's ARS REPORT  ·  "
              f"every day re-checked each run  ·  last checked {stamp}")
    if prev_stamp:
        status += (f"  ·  {len(moved)} changed since the {prev_stamp} check"
                   + (" (listed on each day's bar)" if moved else ""))
    if not use_appstream:
        status += "  ·  (1st-round columns not pulled this run)"
    titles = [f"{TITLE}  ·  THIS WEEK (week of {md(starts[0])})",
              f"LAST WEEK (week of {md(starts[1])})"]
    if dry_run:
        logfn(f"  DRY RUN - nothing written ({len(lay.values)} rows would be)")
        return {"written": False, "rows": len(lay.values), "changed": len(moved),
                "notes": notes}
    write(ws, order, lay, titles, status, logfn)
    return {"written": True, "tab": ws.title, "rows": len(lay.values), "changed": len(moved),
            "changes": [f"{c.date:%a} {md(c.date)}: {c.text}" for c in moved], "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="call_list_to_2nd.run")
    ap.add_argument("--production", action="store_true", help=f"write {PRODUCTION_TAB!r}")
    ap.add_argument("--tab", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-appstream", dest="use_appstream", action="store_false")
    ap.add_argument("--due", action="store_true", help="only offices at their local 1:00 PM")
    ap.add_argument("--only", action="append", help="one owner (repeatable), for checking")
    ap.add_argument("--at", default=None, help="pretend it is this CT time, 'YYYY-MM-DD HH:MM'")
    ap.add_argument("--refresh-index", action="store_true")
    args = ap.parse_args(argv)
    tab = args.tab or (PRODUCTION_TAB if args.production else SANDBOX_TAB)
    now = (dt.datetime.strptime(args.at, "%Y-%m-%d %H:%M").replace(tzinfo=CT)
           if args.at else None)
    res = run(tab=tab, dry_run=args.dry_run, use_appstream=args.use_appstream, due=args.due,
              now=now, only=args.only, refresh_index=args.refresh_index)
    print(f"OK - { {k: v for k, v in res.items() if k != 'notes'} }")
    return 3 if res.get("due") == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
