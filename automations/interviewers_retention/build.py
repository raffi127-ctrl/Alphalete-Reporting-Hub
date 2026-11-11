"""The numbers behind the Interviewers Retention email -- no Google, no browser.

Everything here is a pure function of values already read, so the tests can
feed it a hand-made tab and the run can feed it the real one.

WHERE THE NUMBERS COME FROM
    Weekly podiums + the 4-week columns
        ARS Management 2.0 -> tab 'Interviewers Retention (Interviewer)'.
        A stack of weekly boxes, newest on top (see
        first_to_second_below_mark/source.py for the shape). Per row we read
        '2nd R BOOKED' and '2nd R SHOWED', found by header text.
        Remember the two swapped labels on that tab: col A ('INTERVIEWER') holds
        the OWNER / office and col B ('OFFICE') holds the INTERVIEWER.
        An owner's follow-on rows leave col A blank -- they belong to the owner
        above.
    Yesterday
        The owner's ARS REPORT tab, block '2ND RD SHOWED RETENTION' (Camila's
        Drive), read with call_list_to_2nd.read_second_rounds -- the only place
        with 2nd rounds PER DAY and per interviewer. The weekly tab has no daily
        numbers, so yesterday never comes from it.

THE % IS ALWAYS showed / booked, and the colour is the one Camila grades
2nd-round retention with: >= 50% green, < 50% red (no third colour).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

SOURCE_TAB = "Interviewers Retention (Interviewer)"
BLOCK_MARK = "INTERVIEWERS RETENTION"      # col C of a week box's first row
HEAD_OWNER = "INTERVIEWER"                  # col A of the column-header row
TOTALS_LABEL = "AVERAGES"                   # last row of a box; never an owner
BOOKED_HEADER = "2nd r booked"
SHOWED_HEADER = "2nd r showed"
INTERVIEWER_SUBHEAD = "OFFICE"              # the row above the headers names col B

GOAL = 0.50                                 # >= 50% green, < 50% red
HISTORY_WEEKS = 4                           # Raf: the 4 weeks before this one


# ------------------------------------------------------------------ helpers
def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace(" ", " ")).strip()


def name_key(s: str) -> str:
    """'José  Velazques' -> 'jose velazques': one person, however it's typed."""
    s = unicodedata.normalize("NFKD", norm(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def count(raw) -> int:
    s = norm(raw).replace(",", "")
    try:
        return int(float(s)) if s else 0
    except ValueError:                       # '#DIV/0!', '-', text
        return 0


def pct(showed: int, booked: int) -> Optional[float]:
    return showed / booked if booked else None


def colour(p: Optional[float]) -> str:
    """'good' | 'bad' | '' -- on the WHOLE percent shown, so a cell that reads
    50% is always green (49.6% shows as 50% and is green too)."""
    if p is None:
        return ""
    return "good" if round(p * 100) >= GOAL * 100 else "bad"


def week_start(label: str, today: dt.date) -> Optional[dt.date]:
    """'10/25' -> the Sunday it names. The tab writes no year: take the nearest
    one to today (a label is never months away from the run)."""
    m = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?", norm(label))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    if m.group(3):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            c = dt.date(y, mo, d)
        except ValueError:
            continue
        if best is None or abs((c - today).days) < abs((best - today).days):
            best = c
    return best


# ------------------------------------------------------------ weekly source
@dataclass
class Row:
    owner: str
    interviewer: str
    booked: int
    showed: int


@dataclass
class Week:
    label: str                     # as the tab writes it ('10/25')
    start: Optional[dt.date]       # the Sunday that starts it
    header_row: int                # 1-indexed, for tracing a number back
    rows: List[Row] = field(default_factory=list)

    @property
    def has_second_rounds(self) -> bool:
        return any(r.booked for r in self.rows)


def _cell(row: List, i: Optional[int]) -> str:
    return norm(row[i]) if i is not None and 0 <= i < len(row) else ""


def _find(row: List, want: str) -> Optional[int]:
    for i, c in enumerate(row):
        if norm(c).lower() == want:
            return i
    return None


def parse_weeks(values: List[List], today: dt.date) -> List[Week]:
    """Every week box on the tab, newest first (the tab's own order)."""
    starts = [i for i, r in enumerate(values) if BLOCK_MARK in _cell(r, 2).upper()]
    weeks: List[Week] = []
    for n, s in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(values)
        w = _parse_week(values, s, end, today)
        if w is not None:
            weeks.append(w)
    return weeks


def _parse_week(values, start, end, today) -> Optional[Week]:
    label = _cell(values[start], 0)
    head_i = next((i for i in range(start + 1, min(start + 6, end))
                   if _cell(values[i], 0).upper() == HEAD_OWNER), None)
    if not label or head_i is None:
        return None
    head = values[head_i]
    b_col, s_col = _find(head, BOOKED_HEADER), _find(head, SHOWED_HEADER)
    if b_col is None or s_col is None:
        return None
    # The interviewer column is the one the row above the headers labels
    # 'OFFICE' (the swapped label); col B when that row is missing.
    i_col = next((i for i, c in enumerate(values[head_i - 1])
                  if norm(c).upper() == INTERVIEWER_SUBHEAD), 1)
    wk = Week(label=label, start=week_start(label, today), header_row=start + 1)
    owner = ""
    for i in range(head_i + 1, end):
        r = values[i]
        a = _cell(r, 0)
        if a.upper() == TOTALS_LABEL:
            break
        if a:
            owner = a
        interviewer = _cell(r, i_col)
        if not owner or not interviewer:
            continue
        wk.rows.append(Row(owner, interviewer, count(_cell(r, b_col)),
                           count(_cell(r, s_col))))
    return wk


# --------------------------------------------------------------- the boards
@dataclass
class Line:
    """One row of a podium: an interviewer or an office."""
    name: str
    booked: int = 0
    showed: int = 0
    detail: List[str] = field(default_factory=list)       # their offices / interviewers
    history: List[Optional[float]] = field(default_factory=list)   # oldest -> newest

    @property
    def pct(self) -> Optional[float]:
        return pct(self.showed, self.booked)


def _add(lines: Dict[str, Line], key: str, name: str, b: int, s: int, detail: str):
    ln = lines.setdefault(key, Line(name=name))
    ln.booked += b
    ln.showed += s
    if detail and detail not in ln.detail:
        ln.detail.append(detail)


def by_interviewer(rows: Iterable[Row]) -> Dict[str, Line]:
    out: Dict[str, Line] = {}
    for r in rows:
        _add(out, name_key(r.interviewer), r.interviewer, r.booked, r.showed, r.owner)
    return out


def by_office(rows: Iterable[Row]) -> Dict[str, Line]:
    out: Dict[str, Line] = {}
    for r in rows:
        _add(out, name_key(r.owner), r.owner, r.booked, r.showed, r.interviewer)
    return out


def ranked(lines: Dict[str, Line]) -> List[Line]:
    """Best to worst. Only who had 2nd rounds booked: 0 booked has no %."""
    have = [ln for ln in lines.values() if ln.booked > 0]
    return sorted(have, key=lambda l: (-l.pct, -l.showed, l.name.lower()))


@dataclass
class Board:
    title: str
    subtitle: str
    name_header: str
    lines: List[Line]
    history_labels: List[str] = field(default_factory=list)   # oldest -> newest
    note: str = ""

    @property
    def green(self) -> int:
        return sum(1 for l in self.lines if colour(l.pct) == "good")

    @property
    def red(self) -> int:
        return sum(1 for l in self.lines if colour(l.pct) == "bad")


def md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def week_span(w: Week) -> str:
    if not w.start:
        return f"week of {w.label}"
    return f"week of {md(w.start)} (Sun {md(w.start)} - Sat {md(w.start + dt.timedelta(days=6))})"


def podiums(weeks: List[Week], pick: int = 0) -> Tuple[Board, Board]:
    """The interviewer podium and the office podium for weeks[pick], each row
    carrying the % of the HISTORY_WEEKS weeks before it, oldest to newest."""
    wk = weeks[pick]
    prior = weeks[pick + 1: pick + 1 + HISTORY_WEEKS][::-1]          # oldest first
    labels = [md(w.start) if w.start else w.label for w in prior]
    hist_i = [by_interviewer(w.rows) for w in prior]
    hist_o = [by_office(w.rows) for w in prior]

    def board(lines, hist, title, header) -> Board:
        out = ranked(lines)
        for ln in out:
            k = name_key(ln.name)
            ln.history = [h[k].pct if k in h else None for h in hist]
        return Board(title=title, subtitle=week_span(wk), name_header=header,
                     lines=out, history_labels=labels)

    return (board(by_interviewer(wk.rows), hist_i, "PODIUM BY INTERVIEWER", "Interviewer"),
            board(by_office(wk.rows), hist_o, "PODIUM BY OFFICE", "Office"))


# ---------------------------------------------------------------- yesterday
def yesterday_boards(second: Dict[str, Dict[dt.date, object]], day: dt.date
                     ) -> Tuple[Board, Board, bool]:
    """(by interviewer, by office, has_data) for `day` out of
    call_list_to_2nd.read_second_rounds' {owner: {date: SecondRounds}}.

    has_data False means NOTHING was recorded for that day on any ARS REPORT
    tab: the caller says so in words instead of drawing a table of zeros."""
    ints: Dict[str, Line] = {}
    offs: Dict[str, Line] = {}
    for owner, days in second.items():
        sr = days.get(day)
        if sr is None:
            continue
        for interviewer, (b, s) in getattr(sr, "by", {}).items():
            _add(ints, name_key(interviewer), interviewer, b, s, owner)
            _add(offs, name_key(owner), owner, b, s, interviewer)
    sub = f"{day:%A} {md(day)}"
    bi = Board("YESTERDAY BY INTERVIEWER", sub, "Interviewer", ranked(ints))
    bo = Board("YESTERDAY BY OFFICE", sub, "Office", ranked(offs))
    return bi, bo, bool(bi.lines)
