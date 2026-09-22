r"""Call List to 2nd Round -- the two-week board (Rafael, 2026-09-21).

Rafael's second report after '1st to 2nd Below the Mark': same idea (a board of
days, every office), different funnel stages. It lives in ARS Management 2.0,
next to the Below the Mark tabs, on 'Call List to 2nd Round' (Eve's header row,
first set up as 'Sheet51' on Camila's 'Interviewers Report from R to Z').

THAT WORKBOOK IS NOT EVE'S. This report writes ONLY its own tabs (the board,
its SANDBOX, and their '(picture)' tabs). Every other tab there, and every ARS
REPORT file, is read and never written (Eve, 2026-09-21).

    row 1   THIS WEEK (week of 9/20)          |   LAST WEEK (week of 9/13)
    row 2   status: where the numbers come from, when they were checked
    row 3   Eve's column headers              |   the same, again
            MONDAY 9/21                       |   MONDAY 9/14
            <every office with activity>      |   <every office with activity>
            TUESDAY 9/22 ...                  |   TUESDAY 9/15 ...

WHERE EACH COLUMN COMES FROM (found by header text, never by position)
    Owner Name            'Interviewers Retention (Interviewer)' roster,
                          ARS Management 2.0 (the same owners as Below the Mark)
    Interviewer Name      the owner's ARS REPORT tab, block '2ND RD SHOWED
                          RETENTION': one row per interviewer with 2nd rounds
    Sent to call list     \
    Retention Call list    \  ApplicantStream -> Reports -> Retention Details,
    1st rds booked          > per office, that day's column:
    1st rds showed         /  'Sent to Call List', 'Retention Call List',
    1st rd %              /   'Total First Interviews', 'First Interviews
                              Showed Up', 'Retention First Interviews'
    2nd interviews booked \   the owner's ARS REPORT tab (Camila's Drive), block
    2nd interviews showed  >  '2ND RD SHOWED RETENTION', that day's B and S per
    2nd interview %       /   interviewer; % = S / B -- see parse_second_block

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

# ARS Management 2.0, next to '1st to 2nd below the mark' (Eve moved it there
# 2026-09-21; it started on 'Interviewers Report from R to Z').
SHEET_ID = "1l4Q0SreuddKZrgXwb9MytF-EdPZH-H1hLsa69epq-n8"
PRODUCTION_TAB = "Call List to 2nd Round"          # Eve's header row
SANDBOX_TAB = "Call List to 2nd Round SANDBOX"    # a copy of it; the default target

CT = ZoneInfo("America/Chicago")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]   # Rafael: Mon-Fri
RUN_AT = (13, 0)                       # 1:00 PM local (Rafael); the agent fires at :20
                                       # so it never shares Chrome with Below the Mark
LATE_OK_MIN = 45

TITLE_ROW, STATUS_ROW, HEADER_ROW = 1, 2, 3
FIRST_BODY_ROW = 4
GAP_COLS = 1
TITLE = "CALL LIST TO 2ND ROUND"
# What goes to Slack (Eve, 2026-09-21): ONE picture of ONE day -- the last full
# day (Friday on a Monday). Its own tab so the export is just that day with the
# header on top. Visible on purpose: a hidden tab exports as a blank page.
PICTURE_SUFFIX = " (picture)"

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


# Colour bands: (field, [(lo, hi, colour)]) -- lo inclusive, hi exclusive.
GREEN = {"red": 0.576, "green": 0.769, "blue": 0.490}     # #93C47D
GREY = {"red": 0.800, "green": 0.800, "blue": 0.800}      # #CCCCCC
RED = {"red": 0.918, "green": 0.263, "blue": 0.208}       # #EA4335, as Below the Mark
BANDS = {
    "call_ret": [(None, 0.45, RED), (0.45, 0.50, GREY), (0.50, None, GREEN)],
    "r1": [(None, 0.45, RED), (0.45, 0.50, GREY), (0.50, None, GREEN)],
    "r2": [(None, 0.50, RED), (0.50, None, GREEN)],
}

NAME_WIDTHS = {"owner": 150, "interviewer": 230}

def _hex(h: str) -> dict:
    h = h.lstrip("#")
    return {k: int(h[i:i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}


# Eve (2026-09-21): "ponele bordes a las cajas y un poco más de vida, se ve muy plano".
WEEK_BG = _hex("#1F3864")            # title row: dark navy
DAY_BG = _hex("#2F5597")             # a day that happened: blue
TODAY_BG = _hex("#E69138")           # today, still moving: orange
FUTURE_BG = _hex("#B7B7B7")          # not yet: grey
STATUS_BG = _hex("#DEEAF6")
FIRST_TINT = _hex("#DDE8F8")         # the 1st-round columns (AppStream)
SECOND_TINT = _hex("#EAE0F5")        # the 2nd-round columns (ARS REPORT)
NAME_TINT = _hex("#EDEDED")          # Owner / Interviewer columns: grey (Eve)
# Header cells, pastel, one colour per section (Eve, 2026-09-21).
HEAD_NAME = _hex("#CCCCCC")
HEAD_FIRST = _hex("#A9C4EB")
HEAD_SECOND = _hex("#C9B5E3")
BOX_LINE = _hex("#434343")           # around each day
GROUP_LINE = _hex("#8C8C8C")         # around each office, and between sections
ROW_LINE = _hex("#D9D9D9")           # between an office's interviewers
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
FIRST_FIELDS = ("sent", "call_ret", "b1", "s1", "r1")
SECOND_FIELDS = ("b2", "s2", "r2")
ROW_PX = 22


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


# ------------------------------------ 2nd rounds, from the ARS REPORT's block
# Eve (2026-09-21): the 2nd-round columns come from each owner's tab, block
# '2ND RD SHOWED RETENTION' -- the per-interviewer, per-day numbers Camila's
# sheet already works out -- not counted by us from the applicant log.
#
# The block is a STACK of weekly boxes going down its first column:
#     <week label>  Monday ... Tuesday ... Saturday ... TOTAL for the WEEK
#     Interviewer   B | S | NS | RR | C | R   (per day)   2nd Rd Booked | ...
#     <interviewer> the numbers
#     ...           (a blank row, then the next box)
# Its starting column differs from tab to tab (CM, BZ, BJ), and so does a box's
# height, so everything is found by text: the banner on row 1, the day names on
# a box's label row, 'B' and 'S' under each day.
#
# The week label is the SUNDAY THAT ENDS the week, as in the rest of the ARS
# REPORT files: box '9/27' is Mon 9/21 .. Sat 9/26 (see ars_reports).
SECOND_BANNER = "2ND RD SHOWED RETENTION"
BOOKED_LABEL, SHOWED_LABEL = "B", "S"
_LABEL_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s*$")
_DAY_NAMES = {d.lower(): i for i, d in enumerate(DAYS + ["Saturday"])}   # Monday = 0
NO_INTERVIEWER = "(no interviewer)"


@dataclass
class SecondRounds:
    booked: int = 0
    showed: int = 0
    interviewers: List[str] = field(default_factory=list)       # names in that week's box
    by: Dict[str, List[int]] = field(default_factory=dict)      # interviewer -> [booked, showed]


def _count(raw) -> int:
    try:
        return int(float(str(raw).replace(",", "").strip() or 0))
    except ValueError:
        return 0


def label_week_end(label: str, today: dt.date) -> Optional[dt.date]:
    """'9/27' -> the Sunday it names. No year on the tab: the nearest one to
    today (the boxes run a few weeks ahead of it, never months)."""
    m = _LABEL_RE.match(label or "")
    if not m:
        return None
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = dt.date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def parse_second_block(values: List[List[str]], today: dt.date) -> Dict[dt.date, SecondRounds]:
    """{date: SecondRounds} out of one owner's block, `values` read from the
    banner's column rightwards (row 1 first)."""
    out: Dict[dt.date, SecondRounds] = {}
    i = 0
    while i < len(values):
        row = values[i]
        end = label_week_end(row[0] if row else "", today)
        days = {j: _DAY_NAMES[str(c).strip().lower()] for j, c in enumerate(row)
                if str(c).strip().lower() in _DAY_NAMES}
        if end is None or not days or i + 1 >= len(values):
            i += 1
            continue
        sub = values[i + 1]
        starts = sorted(days)
        cols: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
        for n, j in enumerate(starts):
            stop = starts[n + 1] if n + 1 < len(starts) else j + 8
            span = [(k, str(sub[k]).strip()) for k in range(j, min(stop, len(sub)))]
            b = next((k for k, v in span if v == BOOKED_LABEL), None)
            s = next((k for k, v in span if v == SHOWED_LABEL), None)
            cols[days[j]] = (b, s)
        monday = end - dt.timedelta(days=6)
        names: List[str] = []
        i += 2
        while i < len(values):
            r = values[i]
            first = str(r[0]).strip() if r else ""
            if label_week_end(first, today) is not None and any(
                    str(c).strip().lower() in _DAY_NAMES for c in r):
                break                                   # the next box
            if not first or first.lower() == "interviewer":
                if not any(str(c).strip() for c in r):
                    i += 1
                    if i < len(values) and not any(str(c).strip() for c in values[i]):
                        break                           # two blank rows: the box is over
                    continue
                i += 1
                continue                                # an unnamed totals row
            names.append(first)
            for weekday, (b, s) in cols.items():
                booked = _count(r[b]) if b is not None and b < len(r) else 0
                showed = _count(r[s]) if s is not None and s < len(r) else 0
                if not booked and not showed:
                    continue
                d = monday + dt.timedelta(days=weekday)
                sr = out.setdefault(d, SecondRounds())
                mine = sr.by.setdefault(first, [0, 0])
                mine[0] += booked
                mine[1] += showed
                sr.booked += booked
                sr.showed += showed
            i += 1
        for weekday in cols:
            d = monday + dt.timedelta(days=weekday)
            out.setdefault(d, SecondRounds()).interviewers = list(names)
    return out


def _col_letter(n: int) -> str:            # 0-indexed
    s, n = "", n + 1
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def read_second_rounds(owners: List[str], today: dt.date, *, refresh_index: bool = False,
                       logfn=print) -> Tuple[Dict[str, Dict[dt.date, SecondRounds]], List[str]]:
    """Every owner's 2ND RD block: two batch reads per ARS REPORT workbook (row 1
    to find the banner, then the block itself)."""
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
        heads = sh.values_batch_get([f"'{tab}'!1:1" for _, tab in pairs]).get("valueRanges", [])
        wanted, ranges = [], []
        for (owner, tab), vr in zip(pairs, heads):
            row1 = (vr.get("values") or [[]])[0]
            c = next((j for j, v in enumerate(row1) if SECOND_BANNER in str(v).upper()), None)
            if c is None:
                notes.append(f"{owner} ({book} / {tab}): no '{SECOND_BANNER}' block")
                continue
            # The block runs to the next banner on row 1.
            nxt = next((j for j in range(c + 1, len(row1)) if str(row1[j]).strip()), c + 60)
            wanted.append(owner)
            ranges.append(f"'{tab}'!{_col_letter(c)}1:{_col_letter(nxt - 1)}")
        if not ranges:
            continue
        blocks = sh.values_batch_get(ranges).get("valueRanges", [])
        for owner, vr in zip(wanted, blocks):
            out[owner] = parse_second_block(vr.get("values", []), today)
    logfn(f"  ARS REPORT 2nd-round blocks: {len(out)} of {len(owners)} owners read")
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
    kind: str = "past"    # past | today | future
    rows: int = 0         # data rows under it on this side


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
            kind = "future" if d > today else ("today" if d == today else "past")
            lay.bands.append(Band(row=r, side=side, text=text, kind=kind,
                                  rows=sum(len(g) for g in groups)))
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


# ------------------------------------------------------------ the picture
def last_full_day(today: dt.date) -> dt.date:
    """The last weekday that is over: yesterday, or Friday on a Monday / weekend.
    At 1 PM today is half done, so comparing it with a finished day a week back
    would always make today look worse."""
    d = today - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def picture_band_text(d: dt.date, n: int, changes: Optional[List[Change]] = None) -> str:
    text = f"{d:%A}".upper() + f" {md(d)}"
    text += f"  ·  {n} office{'s' if n != 1 else ''}" if n else "  ·  no activity"
    if changes:
        shown = ", ".join(c.text for c in changes[:BAND_MAX_CHANGES])
        more = len(changes) - BAND_MAX_CHANGES
        text += f"  ·  CHANGED: {shown}" + (f" (+{more} more)" if more > 0 else "")
    return text


def lay_out_picture(order: List[str], blocks: List[Tuple[str, str, List[List[dict]]]]
                    ) -> Layout:
    """One column of day boxes, top to bottom: [(band text, kind, groups)], a
    blank row between boxes."""
    width = len(order)
    lay = Layout(width=width)
    r = FIRST_BODY_ROW
    for n, (text, kind, groups) in enumerate(blocks):
        if n:
            lay.values.append([""] * width)
            r += 1
        rows = sum(len(g) for g in groups)
        lay.bands.append(Band(row=r, side=0, text=text, kind=kind, rows=rows))
        lay.values.append([text] + [""] * (width - 1))
        i = 1
        for group in groups:
            lay.groups.append((r + i, len(group), 0))
            for k, rec in enumerate(group):
                line = [""] * width
                for j, key in enumerate(order):
                    if key and not (k and key in OWNER_FIELDS):
                        v = rec.get(key)
                        line[j] = "" if v is None else v
                lay.values.append(line)
                lay.data_rows.append((r + i, 0))
                i += 1
        r += 1 + rows
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


def write(ws, order: List[str], lay: Layout, titles: List[str], status: str, logfn=print,
          *, sides: int = 2):
    """Write the board (two sides: this week | last week) or the picture (one)."""
    sh = ws.spreadsheet
    sid = ws.id
    width = len(order)
    total = 2 * width + GAP_COLS if sides == 2 else width
    SIDES = range(sides)
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
    wide = max(total, ws.col_count)          # a copied tab can carry more columns
    reqs.append({"updateCells": {"range": _rng(sid, FIRST_BODY_ROW - 1, body_end, 0, wide),
                                 "fields": "userEnteredValue,userEnteredFormat,note"}})
    reqs.append({"updateCells": {"range": _rng(sid, 0, 2, 0, wide),
                                 "fields": "userEnteredValue,userEnteredFormat"}})
    if sides == 2:
        # Last week's header: a copy of Eve's, look and all.
        reqs.append({"copyPaste": {"source": _rng(sid, HEADER_ROW - 1, HEADER_ROW, 0, width),
                                   "destination": _rng(sid, HEADER_ROW - 1, HEADER_ROW,
                                                       width + GAP_COLS, total),
                                   "pasteType": "PASTE_NORMAL"}})
    elif wide > width:
        reqs.append({"updateCells": {"range": _rng(sid, HEADER_ROW - 1, HEADER_ROW, width, wide),
                                     "fields": "userEnteredValue,userEnteredFormat,note"}})
    # ...then each header cell in its section's pastel, bold.
    for side in SIDES:
        c0 = side * (width + GAP_COLS)
        for j, key in enumerate(order):
            bg = (HEAD_FIRST if key in FIRST_FIELDS else HEAD_SECOND if key in SECOND_FIELDS
                  else HEAD_NAME if key in ("owner", "interviewer") else None)
            if bg:
                reqs.append({"repeatCell": {
                    "range": _rng(sid, HEADER_ROW - 1, HEADER_ROW, c0 + j, c0 + j + 1),
                    "cell": {"userEnteredFormat": {"backgroundColor": bg,
                                                   "textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold"}})
    for side in SIDES:
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
        # NO notes on the header: a note prints at the foot of the exported
        # picture ("[1] 50%+ green ..."). The colour rules go in the Slack
        # message instead (slack_post.message). Clear any left from before.
        reqs.append({"updateCells": {
            "range": _rng(sid, HEADER_ROW - 1, HEADER_ROW, c0, c0 + width), "fields": "note"}})
    # Body: numbers centred, percents as percents, a light grid.
    body = _rng(sid, FIRST_BODY_ROW - 1, last, 0, total)
    reqs.append({"repeatCell": {"range": body, "cell": {"userEnteredFormat": {
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
        "textFormat": {"fontSize": 10}}}, "fields": "userEnteredFormat"}})
    for side in SIDES:
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
    # Section tints: the 1st-round columns one colour, the 2nd-round another,
    # so the eye splits the row in two without reading the header.
    for row, side in lay.data_rows:
        c0 = side * (width + GAP_COLS)
        reqs.append({"updateBorders": {"range": _rng(sid, row - 1, row, c0, c0 + width),
            **{k: {"style": "SOLID", "color": ROW_LINE}
               for k in ("top", "bottom", "left", "right", "innerVertical")}}})
        for j, key in enumerate(order):
            tint = (FIRST_TINT if key in FIRST_FIELDS else SECOND_TINT if key in SECOND_FIELDS
                    else NAME_TINT if key in ("owner", "interviewer") else None)
            if tint:
                reqs.append({"repeatCell": {"range": _rng(sid, row - 1, row, c0 + j, c0 + j + 1),
                    "cell": {"userEnteredFormat": {"backgroundColor": tint}},
                    "fields": "userEnteredFormat.backgroundColor"}})
        oj = order.index("owner")
        reqs.append({"repeatCell": {"range": _rng(sid, row - 1, row, c0 + oj, c0 + oj + 1),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"}})
        reqs.append({"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "ROWS", "startIndex": row - 1, "endIndex": row},
            "properties": {"pixelSize": ROW_PX}, "fields": "pixelSize"}})
    for first, rows, side in lay.groups:
        c0 = side * (width + GAP_COLS)
        if rows > 1:
            for j, key in enumerate(order):
                if key in OWNER_FIELDS:
                    reqs.append({"mergeCells": {"range": _rng(sid, first - 1, first - 1 + rows,
                                                              c0 + j, c0 + j + 1),
                                                "mergeType": "MERGE_ALL"}})
        # Each office is a box; the 1st- and 2nd-round sections are split by a line.
        box = _rng(sid, first - 1, first - 1 + rows, c0, c0 + width)
        reqs.append({"updateBorders": {"range": box, **{
            k: {"style": "SOLID_MEDIUM", "color": GROUP_LINE}
            for k in ("top", "bottom", "left", "right")}}})
        for key in (FIRST_FIELDS[0], SECOND_FIELDS[0]):
            j = order.index(key)
            reqs.append({"updateBorders": {
                "range": _rng(sid, first - 1, first - 1 + rows, c0 + j, c0 + j + 1),
                "left": {"style": "SOLID_MEDIUM", "color": GROUP_LINE}}})
    for b in lay.bands:
        c0 = b.side * (width + GAP_COLS)
        rng = _rng(sid, b.row - 1, b.row, c0, c0 + width)
        reqs.append({"mergeCells": {"range": rng, "mergeType": "MERGE_ALL"}})
        bg = {"today": TODAY_BG, "future": FUTURE_BG}.get(b.kind, DAY_BG)
        reqs.append({"repeatCell": {"range": rng, "cell": {"userEnteredFormat": {
            "backgroundColor": bg, "horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE",
            "padding": {"left": 8},
            "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE}}},
            "fields": "userEnteredFormat"}})
        # The whole day -- its bar and its offices -- inside one thick box.
        reqs.append({"updateBorders": {
            "range": _rng(sid, b.row - 1, b.row + b.rows, c0, c0 + width),
            **{k: {"style": "SOLID_THICK", "color": BOX_LINE}
               for k in ("top", "bottom", "left", "right")}}})
        reqs.append({"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "ROWS", "startIndex": b.row - 1, "endIndex": b.row},
            "properties": {"pixelSize": 28}, "fields": "pixelSize"}})
    # Colours: the whole column, both weeks.
    for key, bands in BANDS.items():
        j = order.index(key)
        ranges = [_rng(sid, FIRST_BODY_ROW - 1, last, s * (width + GAP_COLS) + j,
                       s * (width + GAP_COLS) + j + 1) for s in SIDES]
        letter = _a1col(j + 1)
        for lo, hi, colour in bands:
            reqs.append(_band_rule(sid, ranges, lo, hi, colour, letter, FIRST_BODY_ROW))
    if sides == 2:
        reqs.append({"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": width,
            "endIndex": width + GAP_COLS},
            "properties": {"pixelSize": 24}, "fields": "pixelSize"}})
    # Names have to read whole: the owner and interviewer columns are widened.
    for side in SIDES:
        c0 = side * (width + GAP_COLS)
        for key, px in NAME_WIDTHS.items():
            j = order.index(key)
            reqs.append({"updateDimensionProperties": {"range": {
                "sheetId": sid, "dimension": "COLUMNS", "startIndex": c0 + j, "endIndex": c0 + j + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    sh.batch_update({"requests": reqs})

    top = [[""] * total, [""] * total]
    for side in SIDES:
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

    # The board as it stands: the "before" for what moved, and the numbers of
    # the offices a --due pass does not pull.
    board = ws if ws is not None else next(
        (w for w in sh.worksheets() if w.title.strip().lower() == tab.strip().lower()), None)
    before = board.get_all_values(value_render_option="UNFORMATTED_VALUE") if board else []
    prev = read_back(before, order, start.year) if before else {}
    prev_stamp = prior_stamp(before)
    kept = prev if set(to_pull) != set(owners) else {}

    # The picture's day: the last full day (Friday on a Monday). Always on the
    # board -- this week or last week -- so nothing extra to pull.
    pic_day = last_full_day(today)

    logs, notes = read_second_rounds(to_pull, today, refresh_index=refresh_index, logfn=logfn)
    as_data: Dict[Tuple[str, dt.date], dict] = {}
    if use_appstream and to_pull:
        try:
            as_data, gaps = fetch_appstream(to_pull, starts, logfn=logfn)
            notes.extend(gaps)
        except Exception as exc:                          # noqa: BLE001
            notes.append(f"AppStream unavailable: {type(exc).__name__}: {exc}")
            logfn(f"  !! AppStream unavailable ({type(exc).__name__}: {exc})")
    elif not use_appstream:
        # No AppStream this run (Windows has no session): keep the 1st-round
        # numbers the board already shows rather than blanking every office.
        as_data = {k: {f: g[0].get(f) for f in AS_ROWS} for k, g in prev.items()}

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
        status += "  ·  (1st-round columns as of the last AppStream check)"
    titles = [f"{TITLE}  ·  THIS WEEK (week of {md(starts[0])})",
              f"LAST WEEK (week of {md(starts[1])})"]
    # The picture: this pass's offices (everybody on a full run), fresh.
    def pic_groups(d: dt.date) -> List[List[dict]]:
        out = []
        for o in owners:
            if o not in to_pull:
                continue
            g = make_group(o, roster.get(o, []), as_data.get((o, d)),
                           (logs.get(o) or {}).get(d))
            if g:
                out.append(g)
        return out

    # ONE day only (Eve, 2026-09-21: the comparison with last week made the
    # picture too long).
    day_groups = pic_groups(pic_day)
    pic_lay = lay_out_picture(order, [
        (picture_band_text(pic_day, len(day_groups), changes.get(pic_day)), "past",
         day_groups)])
    pic_title = f"{TITLE}  ·  {pic_day:%A} {md(pic_day)}"
    if due:
        # Say whose picture this is: each time zone's pass posts its own.
        from automations.first_to_second_below_mark import office_tz as tz
        zones = sorted({tz.label(tz.zone_or_fallback(o)[0]) for o in to_pull})
        pic_title += f"  ·  {' + '.join(zones)} offices"
    if dry_run:
        logfn(f"  DRY RUN - nothing written ({len(lay.values)} rows would be)")
        return {"written": False, "rows": len(lay.values), "changed": len(moved),
                "notes": notes}
    write(ws, order, lay, titles, status, logfn)
    pic_tab = ws.title + PICTURE_SUFFIX
    try:
        pic_ws = fill.worksheet_ci(sh, pic_tab)
    except Exception:                                     # noqa: BLE001
        logfn(f"  creating {pic_tab!r}")
        pic_ws = sh.duplicate_sheet(ws.id, new_sheet_name=pic_tab)
    write(pic_ws, order, pic_lay, [pic_title], status, logfn, sides=1)
    return {"picture_tab": pic_tab, "written": True, "tab": ws.title, "rows": len(lay.values), "changed": len(moved),
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
