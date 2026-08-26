"""Finding the CHARTS on a D2D OBCL tab — one implementation, several readers.

Both `blueink_docs` and `headshots` read the dated "D2D OBCL <m.d>" tabs of
Raf's All in One Local Office workbook, and both were parsing them separately.
That meant every lesson had to be learned twice; on 2026-08-24 the Blue Ink
reader was fixed for two of these and the headshot reader still had both.

WHAT A CHART IS (Megan's word for it, 2026-08-24): a date row, a header row,
then people — and **only people inside a chart count**. A tab holds more than
one; Monday's reliably holds two, the second being the late adds.

    8/24/2026                <- date row, opens a chart
    #  Interviewer  Name …   <- header row, names the columns
    1  …           Ana  …    <- people
    2  …           Ben  …
                             <- BLANK ROW closes the chart
    8/24/2026                <- a second chart opens
    #  Interviewer  Name …
    1  …           Cal  …

Three rules, each of them a bug someone actually hit:

1. **A chart ends at a BLANK ROW.** Letting a chart run to the next header (or
   to the bottom of the tab) means anything typed underneath reads as one of
   its people. On 2026-08-24 that turned 25 stray name rows below the chart
   into fake people with no email address.
2. **A chart opened by a DATE ROW with no header of its own inherits the
   previous chart's columns.** Monday's second chart is often pasted in without
   one, and its people would otherwise vanish silently.
3. **Columns are found by header LABEL, never by index.** These tabs get
   re-sorted and columns get inserted mid-week — a "Blue Ink" column appeared
   on 8/24 and shifted everything after it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

_DATE_RE = re.compile(r"^\s*\d{1,2}[./]\d{1,2}([./]\d{2,4})?\s*$")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def is_blank_row(row: List[str]) -> bool:
    return not any((c or "").strip() for c in row)


def is_date_row(row: List[str]) -> bool:
    return bool(row) and bool(_DATE_RE.match((row[0] or "") if row else ""))


def is_header_row(row: List[str], first_label: str, last_label: str) -> bool:
    cells = [norm(c).lower() for c in row]
    return first_label.lower() in cells and last_label.lower() in cells


def find_charts(values: List[List[str]], *, first_label: str = "Name",
                last_label: str = "Last Name") -> List[Dict]:
    """Every chart on the tab, in order.

    Each entry: {"header_row", "start_row", "end_row", "cols", "date_text"}
    with 1-indexed rows; `end_row` is inclusive and stops at the blank row that
    closes the chart. `cols` maps the normalised header label -> 1-indexed
    column.

    `date_text` is the date row VERBATIM ("8/24/2026", or "8/24" when the year
    is left off), or "" for a chart no date row opened. It used to be thrown
    away — the parser recognised a date row only to know a chart was starting.
    Digi Docs needs it: it fires on the day a chart is dated for, and "it is
    Monday" was only ever true by coincidence (Megan 2026-08-26). Use
    `chart_date()` to turn it into a real date.
    """
    charts: List[Dict] = []
    cur: Optional[Dict] = None
    last_cols: Optional[Dict] = None
    pending_date = False
    pending_date_text = ""

    def close(at_row: int) -> None:
        nonlocal cur
        if cur is not None:
            cur["end_row"] = at_row
            charts.append(cur)
            cur = None

    for i, row in enumerate(values):
        rownum = i + 1
        if is_blank_row(row):
            close(rownum - 1)
            pending_date = False
            pending_date_text = ""
            continue
        if is_header_row(row, first_label, last_label):
            close(rownum - 1)
            cols = {norm(c): j + 1 for j, c in enumerate(row) if norm(c)}
            cur = {"header_row": rownum, "start_row": rownum + 1, "cols": cols,
                   "date_text": pending_date_text}
            last_cols = cols
            pending_date = False
            pending_date_text = ""
            continue
        if is_date_row(row):
            # Opens a chart. If a header follows it takes over; if none does,
            # rule 2 lets this chart borrow the last one's columns.
            close(rownum - 1)
            pending_date = True
            pending_date_text = norm(row[0])
            continue
        if cur is None and pending_date and last_cols:
            cur = {"header_row": None, "start_row": rownum,
                   "cols": dict(last_cols), "date_text": pending_date_text}
            pending_date = False
            pending_date_text = ""
        # a row with no chart open belongs to nobody -- rule 1

    close(len(values))
    return charts


def chart_date(chart: Dict, tab_name: str = ""):
    """The real date a chart is FOR, or None.

    The date row is written "8/24/2026" or, often, just "8/24" — so when the
    year is missing it comes from the tab name ("D2D OBCL 8.24"), and failing
    that from today. Getting the year wrong by inference is harmless here: the
    only question asked of this is "is that date today", and a wrong year
    answers no, which withholds a send rather than mistiming one.
    """
    import datetime as _dt
    text = norm(chart.get("date_text") or "")
    if not text:
        return None
    parts = re.split(r"[./]", text)
    if len(parts) < 2:
        return None
    try:
        month, day = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    year = None
    if len(parts) > 2:
        try:
            year = int(parts[2])
            if year < 100:
                year += 2000
        except ValueError:
            year = None
    if year is None:
        m = re.search(r"(\d{4})", tab_name or "")
        year = int(m.group(1)) if m else _dt.date.today().year
    try:
        return _dt.date(year, month, day)
    except ValueError:
        return None


def chart_for_row(charts: List[Dict], row: int) -> Optional[Dict]:
    """The chart a 1-indexed sheet row belongs to, or None if it is outside
    every chart — which, per rule 1, means it belongs to nobody."""
    for c in charts:
        if c["start_row"] <= row <= (c.get("end_row") or c["start_row"]):
            return c
    return None


def column(chart: Dict, label: str) -> Optional[int]:
    """1-indexed column whose header CONTAINS `label` (case-insensitive).

    Contains, not equals: the real BG header reads "\\nBG Status : Last Checked ".
    """
    want = label.strip().lower()
    for head, col in chart.get("cols", {}).items():
        if want in head.lower():
            return col
    return None
