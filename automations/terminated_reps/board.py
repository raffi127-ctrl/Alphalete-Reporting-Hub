"""Read TERMINATED reps off the Alphalete SALES BOARD 2025.

Source: workbook 'Alphalete SALES BOARD 2025'
(1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc), one tab per week named
'Sales Board WE <M>.<D>' where <M>.<D> is the week's SUNDAY (so 'WE 8.9' is
Mon 8/3 → Sun 8/9).

A tab carries TWO populations, and they mark a termination in THREE DIFFERENT
WAYS. All of them have to be read or most of the terminations are missed — the
tenured roster never shows the word 'Terminated' anywhere, the new starts never
get a Termination Date, and the roster's own 'Termination Date' column is left
blank far more often than it is filled:

  1. THE ROSTER (top block, from the header row down to the 'New Starts/Raf'
     label). Terminated = the per-rep 'Termination Date' column is filled in.
     '# Days Worked' sits beside it and is a live formula
     (=IF(<term>=0, TODAY()-<start>, <term>-<start>)) — we read its VALUE, we
     never recompute it, so the tracker always agrees with the board.
     Verified 2026-08-07 against the tracker: Adriannah Reyes (Wk 3) 16 days /
     8-5, Emmanuel Nieto 4 / 8-4, Jade Sapp (Wk 2) 7 / 8-3.

  1b. THE ROSTER'S 'T' MARKS — the same rows, when nobody filled the date in.
     A bare 'T' typed into ANY column of a day block means terminated from that
     day, and the day block it lands in is the date. It is NOT reliably the
     roll-call column: it turns up in 'Apps', in 'Int', across the whole block,
     or in the roll call alone. On WE 8.23 fifteen roster rows carried T marks
     and NOT ONE had a Termination Date — reading only the date column filed
     none of them (Eve, 2026-08-24).
     When a T sits next to a cell that contradicts it (a real roll-call status,
     a non-zero metric), or when the date column says a different week from the
     T marks, the row is NOT filed — it comes back as a `Check` for Eve.

  2. THE 'New Starts/Raf' BOX (bottom). No dates, no days column — just a
     roll-call cell per weekday, and a terminated new start reads
     'Terminated' from their last day onward. So:
        termination date = the FIRST 'Terminated' weekday column
        # days worked    = that weekday's offset from Monday
     which is exactly what the tracker holds: Alexa Loredo 'Terminated' from
     Tuesday → 1 day / 8-4; Kayla Ramirez from Wednesday → 2 days / 8-5.

EVERYTHING IS FOUND BY LABEL — the week tab by its WE date, the rep column by
the 'WE m/d- m/d' header, the date/days columns by their row-1 titles, the box
by its 'New Starts/Raf' label and its own weekday header row. The board gains
and loses rows every week and the two blocks do not even share a column layout
(the roster's day blocks are 8 columns wide starting at MON; the box's are one
column per day, offset by one block), so positional lookups would rot on the
first inserted row. [[no hardcoded rows or columns]]

Read UNFORMATTED: dates come back as serials and '# Days Worked' as a number,
so nothing depends on the viewer's date locale.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Iterable

from automations.recruiting_report.fill import open_by_key

SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"

WE_TAB_RE = re.compile(r"^\s*sales board we\s+(\d{1,2})\.(\d{1,2})\s*$")
# The roster's rep column is headed with the week it covers: 'WE 8/3- 8/9'.
WE_HEADER_RE = re.compile(r"^we\s+\d{1,2}/\d{1,2}\s*-")

COL_DAYS_WORKED = "# days worked"
COL_TERM_DATE = "termination date"
COL_START_DATE = "start date"
BOX_LABEL = "new starts/raf"
BOX_NAME_HEADER = "classroom"
TERMINATED = "terminated"
ROLL_CALL = "roll call"

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}

# The roster's own day headers, on ROW 1, above each 8-column day block:
# 'MON' at 26, 'TUES' at 34 … 'SUN' at 74. Short and long forms both, because
# 'MON'/'MONDAY' are one rename apart. When two labels fold to the same weekday
# the LEFTMOST wins — row 1 carries 'SUN' at the head of the block and a
# separate per-rep 'Sunday' column right after it, and only the first is a day.
DAY_LABELS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
              "wed": 2, "weds": 2, "wednesday": 2, "thu": 3, "thur": 3,
              "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
              "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}

# HOW A TERMINATION IS MARKED INSIDE A DAY BLOCK. Whoever closes the board out
# types a bare 'T' — and NOT always in the same column. Most weeks it goes in
# the day's 'Roll Call' cell, but it also lands in 'Apps'/'Int' with the roll
# call left on the attendance value it already had (Anh Dinh, WE 8.16), and on
# some rows every cell of the block reads 'T'. So a termination is 'a T
# ANYWHERE in the day block', not 'a T in the roll-call column'
# (Eve, 2026-08-24). Reading only the roll call missed 15 of the 15 terminated
# rows on WE 8.23 — none of them had a Termination Date either.
TERM_MARKS = {"t", "terminated"}

# Cell values that carry NO information, so a 'T' sitting next to them is not a
# contradiction: blanks, the 'X'/'x' the board types for a rep with nothing to
# report, a zero count, an unticked checkbox. Anything else in the same block as
# a 'T' — a real roll-call status ('Here', 'H+DC', 'Off', 'STF'…) or a NON-zero
# metric — is the board disagreeing with itself, and that gets flagged for Eve
# instead of filed. [[see Check]]
NEUTRAL_MARKS = {"", "x", "-", "--", "n/a", "na", "true", "false", "0"}

# How a new start's FIRST 'Terminated' weekday maps to the date and day count
# Eve files. 0 = take the column at face value; 1 = the day after it.
#
# THE BOARD AND THE TRACKER DISAGREE, so this is a setting, not a derivation.
# Measured over WE 7.5 → 8.9 (2026-08-07) against the rows Eve filed by hand:
#     offset 1 reproduces 83 box rows, offset 0 reproduces 17.
# Nothing on the board distinguishes the two groups — the box's weekday headers
# are byte-identical across every week, and NO ONE terminated in the box ever
# picks up a roster 'Termination Date' that could break the tie (checked across
# 7 weeks: 125 box terminations, 61 roster, zero overlap). The likeliest reading
# is that Eve used to file the morning AFTER the board showed 'Terminated' and
# now files same-day.
#
# 0 IS THE DEFAULT ANYWAY, because the 17 are the RECENT ones — all of WE 8.9
# and part of 7.19 — and matching current practice is what keeps this from
# fighting her. Offset 1 would have refiled all five of WE 8.9's new starts one
# day later as DUPLICATES of rows she had already entered. It also stops dating
# terminations into the future: a rep marked today came out as tomorrow.
# Flip to 1 if the tracker should carry the day the termination is PROCESSED
# rather than the day the board shows it.
BOX_DAY_OFFSET = 0

# Google's serial-date epoch (it treats 1900 as a leap year, hence Dec 30).
_EPOCH = dt.date(1899, 12, 30)


class BoardLayoutError(RuntimeError):
    """A label the reader needs isn't on the tab. Raised instead of guessing a
    column — a wrong guess would file real people under wrong dates."""


@dataclass(frozen=True)
class Termination:
    """One terminated rep as the board states it."""
    name: str
    term_date: dt.date
    days_worked: int | None      # None when the board leaves it blank
    source: str                  # 'roster' | 'roster T' | 'new starts'
    tab: str
    row: int                     # 1-indexed row on the tab, for the audit trail

    @property
    def key(self) -> tuple[str, dt.date]:
        """Dedupe identity. A rep CAN legitimately appear twice with two
        different dates (rehired then let go again — Myra Singleton 7/31 and
        8/3 both sit in the tracker), so the date is part of the key."""
        return (norm_name(self.name), self.term_date)


# The order dedupe() prefers when the same person+date turns up more than once.
# A filled Termination Date beats a 'T' mark (it is the only signal that carries
# a real day count), and both beat the new-starts box (whose day count only
# spans the current week).
SOURCE_RANK = {"roster": 0, "roster T": 1, "new starts": 2}


@dataclass(frozen=True)
class Check:
    """A row the board can't be trusted about — Eve looks and says which it is.

    Two things produce one, both of them 'the board contradicts itself':

      * MIXED DAY. The first day marked 'T' also holds a cell that says the rep
        was working — a real roll-call status or a non-zero metric. Kaleb
        Muvunyi on WE 8.23 has Roll Call 'T' on Wednesday and Thursday while
        Apps and Int both read 1 on those same days.
      * DATE DISAGREEMENT. The row has a Termination Date AND T marks, and they
        point at days more than 24h apart (Caleb Rink, WE 8.2: date column says
        8/2, the T marks start 7/27).

    Nothing is filed and nothing is dated from a Check — it is posted in the
    week's thread as its own 'check this' message and printed in the run log.
    Guessing would put a real person on the tracker under a day nobody agrees on.

    `proposed` is what a ✅ on that message means (Eve, 2026-08-24). The two
    kinds of Check need different answers, and the message has to say which:

      * MIXED DAY — nothing was filed, so `proposed` is the exact Termination a
        ✅ files: name, date and day count spelled out in the message BEFORE the
        reaction, so the tick confirms a specific row rather than a vague "yes".
      * DATE DISAGREEMENT — the row is already on the tracker under the date
        column's day (see scan_grid: the check is raised and the row is filed
        anyway). `proposed` is None: there is nothing left to file and a ✅ only
        says "I looked". Filing off this one would duplicate a real person.
    """
    name: str
    tab: str
    row: int
    reason: str
    marked_date: dt.date | None      # what the T marks say
    board_date: dt.date | None       # what the 'Termination Date' column says
    proposed: "Termination | None" = None   # the row a ✅ files; None = already filed

    @property
    def key(self) -> tuple[str, str]:
        return (norm_name(self.name), self.reason)


def norm_name(s: str) -> str:
    """Fold a name for comparison only — never for writing. Handles the
    non-breaking spaces and stray tabs that pasted names carry
    ('Gabriel\\xa0 Armando Rivera', 'Christian\\tWilliams')."""
    return " ".join(str(s or "").replace("\xa0", " ").replace("\t", " ").split()).lower()


_PAREN = re.compile(r"\([^)]*\)")


def base_name(s: str) -> str:
    """`norm_name` with the parentheticals dropped, for recognising the SAME
    PERSON across two week tabs.

    The board re-labels people week to week — 'Jaylen (Ash) Walker (Wk 3)' on
    WE 8.23 is plain 'Jaylen (Ash) Walker' on WE 8.30 — so the '(Wk n)' marker
    has to come off before the two can be compared. It is NOT used for the
    tracker's dedupe key: that one is written to a Sheet Eve reads, and folding
    away a middle name there would merge two different people."""
    return " ".join(_PAREN.sub(" ", norm_name(s)).split())


def _norm(s) -> str:
    return " ".join(str(s if s is not None else "").replace("\xa0", " ").split()).strip().lower()


def _cell(grid: list, row: int, col: int):
    """1-indexed grid access that tolerates ragged rows (the API truncates
    trailing empties, so row lengths differ)."""
    if 1 <= row <= len(grid):
        r = grid[row - 1]
        if 1 <= col <= len(r):
            return r[col - 1]
    return ""


def to_date(value) -> dt.date | None:
    """A cell → date. Serial number (the UNFORMATTED read) or, defensively, a
    m/d/Y-ish string if someone ever reads this tab formatted."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return _EPOCH + dt.timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    s = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _roster_days(days_cell, start_cell) -> int | None:
    """The roster's '# Days Worked', or None when the board can't know it.

    The column is =IF(<term>=0, TODAY()-<start>, <term>-<start>), and a rep
    whose START DATE was never filled in makes that subtract from zero: the
    cell then reads ~46232, which is the termination DATE's serial, not a
    tenure. Two people on WE 8.2 (Adrian Alonso Leos, Gabriel Armando Rivera)
    look exactly like that, and Eve left both blank on the tracker by hand —
    so a missing start date means blank, not a five-digit day count.

    The magnitude check is a second net for a start date that is present but
    garbage (a text date, a typo'd year): nobody has worked 20,000 days."""
    if to_date(start_cell) is None:
        return None
    n = _to_int(days_cell)
    if n is None or n < 0 or n > 20000:
        return None
    return n


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- week tabs

def week_sunday(day: dt.date) -> dt.date:
    """The Sunday that CLOSES the week `day` falls in — the board's weeks run
    Monday→Sunday and each tab is named for its Sunday."""
    return day + dt.timedelta(days=(6 - day.weekday()) % 7)


def _resolve_tab_date(month: int, day: int, today: dt.date) -> dt.date | None:
    """A tab label carries no year ('WE 8.9'), so pick the candidate year whose
    date lands closest to today. Keeps the January tabs of a new year from
    resolving twelve months into the past."""
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cand = dt.date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - today).days) < abs((best - today).days):
            best = cand
    return best


def week_tabs(sh, today: dt.date) -> list[tuple[dt.date, str]]:
    """Every 'Sales Board WE m.d' tab as (sunday, title), newest last."""
    out = []
    for ws in sh.worksheets():
        m = WE_TAB_RE.match(_norm(ws.title))
        if not m:
            continue
        d = _resolve_tab_date(int(m.group(1)), int(m.group(2)), today)
        if d:
            out.append((d, ws.title))
    return sorted(out)


def pick_tab(sh, today: dt.date, want: str | None = None) -> str:
    """The tab to read: the one for today's week, else the most recent one.

    Falling back to the newest tab rather than failing is deliberate — the
    board's week tab is created by hand on Monday morning and the daily run
    fires before that on some weeks. Reading last week's tab one more time is
    harmless (everything on it is already in the tracker); refusing to run
    would silently skip a day of terminations."""
    tabs = week_tabs(sh, today)
    if not tabs:
        raise BoardLayoutError(
            "No 'Sales Board WE <m>.<d>' tab in the SALES BOARD workbook.")
    if want:
        for d, title in tabs:
            if _norm(title) == _norm(want) or _norm(title).endswith(f"we {_norm(want)}"):
                return title
        raise BoardLayoutError(
            f"No week tab matching {want!r}. Have: "
            f"{', '.join(t for _, t in tabs[-6:])}")
    target = week_sunday(today)
    for d, title in tabs:
        if d == target:
            return title
    newest_d, newest = tabs[-1]
    print(f"  ⚠ no tab for the week ending {target.month}.{target.day} — "
          f"reading the most recent one, {newest!r} "
          f"(week ending {newest_d.isoformat()})")
    return newest


# ------------------------------------------------------------------- layout

@dataclass(frozen=True)
class Layout:
    header_row: int
    name_col: int
    days_col: int
    term_col: int
    start_col: int
    box_label_row: int
    box_header_row: int
    box_first_row: int
    box_name_col: int
    box_days: tuple[tuple[int, int], ...]   # (column, weekday offset Mon=0)
    # (weekday offset Mon=0, first column, last column) for each of the roster's
    # day blocks — 'MON' spans 26..33, 'TUES' 34..41 and so on. The whole block
    # is scanned for 'T' marks, because the mark is not tied to one column.
    day_blocks: tuple[tuple[int, int, int], ...] = ()
    # Same, for the New Starts box's own (offset) day columns.
    box_blocks: tuple[tuple[int, int, int], ...] = ()

    @property
    def roster_rows(self) -> range:
        return range(self.header_row + 1, self.box_label_row)


def _blocks(day_cols: Iterable[tuple[int, int]]) -> tuple[tuple[int, int, int], ...]:
    """(column, weekday) pairs → (weekday, first column, last column) spans.

    A block runs from its own day label up to the column before the NEXT day
    label. The last one has no neighbour to stop it, so it borrows the width the
    other blocks agree on (8 on every tab since WE 6.7) — never 'to the end of
    the row', which would swallow the per-rep columns ('Trainer', 'Field
    Status', '# Days Worked'…) that sit immediately after Sunday.
    """
    seen: dict[int, int] = {}
    for col, off in sorted(day_cols):
        seen.setdefault(off, col)          # leftmost label wins the weekday
    starts = sorted((col, off) for off, col in seen.items())
    if not starts:
        return ()
    widths = [starts[i + 1][0] - starts[i][0] for i in range(len(starts) - 1)]
    last = max(set(widths), key=widths.count) if widths else 8
    out = []
    for i, (col, off) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else col + last - 1
        out.append((off, col, end))
    return tuple(sorted(out))


def _mark(value) -> str:
    """A cell folded for mark comparison. Numbers keep their value ('0' is
    neutral, '1' is a rep who worked), text loses case and padding."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value) == int(value) else str(value)
    return " ".join(str(value if value is not None else "").replace("\xa0", " ").split()).lower()


@dataclass(frozen=True)
class DayMark:
    """One day block of one row, once the 'T' marks in it have been counted."""
    offset: int                              # Mon=0
    marks: tuple[int, ...]                   # columns reading 'T'/'Terminated'
    conflicts: tuple[tuple[int, str], ...]   # (column, value) that disagree


def day_marks(grid: list, row: int, blocks) -> list[DayMark]:
    """Every day block of `row` that carries a termination mark, in day order.

    A block with no 'T' anywhere is not returned at all. `conflicts` holds the
    cells in the SAME block that say the rep was working — that is what turns a
    termination into a Check instead of a filing."""
    out = []
    for off, c0, c1 in blocks:
        marks, conflicts = [], []
        for c in range(c0, c1 + 1):
            v = _mark(_cell(grid, row, c))
            if v in TERM_MARKS:
                marks.append(c)
            elif v not in NEUTRAL_MARKS:
                conflicts.append((c, v))
        if marks:
            out.append(DayMark(off, tuple(marks), tuple(conflicts)))
    return out


def find_layout(grid: list) -> Layout:
    """Locate both blocks by label. Raises BoardLayoutError naming the label it
    couldn't find, so a renamed header reads as a one-line fix rather than a
    stack trace."""
    # The roster header row, anchored on the rank column's '#'. Every tab back
    # to WE 6.7 has it; the friendlier 'WE 8/3- 8/9' label over the names does
    # NOT (whoever built WE 8.2 left that cell blank), so '#' is the anchor and
    # the WE label is only used to confirm which column the names are in.
    header_row = rank_col = 0
    for r in range(1, min(len(grid), 12) + 1):
        for c in range(1, len(grid[r - 1]) + 1):
            if _norm(_cell(grid, r, c)) == "#":
                header_row, rank_col = r, c
                break
        if header_row:
            break
    if not header_row:
        raise BoardLayoutError(
            "Couldn't find the roster header row — no '#' rank column in the "
            "first 12 rows.")
    name_col = next((c for c in range(1, len(grid[header_row - 1]) + 1)
                     if WE_HEADER_RE.match(_norm(_cell(grid, header_row, c)))),
                    rank_col + 1)
    # Prove it really is the names before reading dates against it: a shifted
    # column would file every termination under the wrong person.
    peek = [str(_cell(grid, r, name_col) or "").strip()
            for r in range(header_row + 1, header_row + 21)]
    if sum(1 for v in peek if v and not v.replace(".", "").isdigit()) < 5:
        raise BoardLayoutError(
            f"Column {name_col} (right of the '#' in row {header_row}) doesn't "
            f"look like rep names — got {peek[:6]}. Layout changed; fix the "
            "anchor before filing anyone.")

    # The per-rep columns are titled on ROW 1, above the day blocks.
    titles = {_norm(v): i for i, v in enumerate(grid[0], 1) if _norm(v)}
    missing = [t for t in (COL_DAYS_WORKED, COL_TERM_DATE, COL_START_DATE)
               if t not in titles]
    if missing:
        raise BoardLayoutError(
            f"Row 1 is missing the column title(s) {missing} — the roster's "
            f"termination signal lives there. Found: "
            f"{sorted(t for t in titles if t)[:25]}")

    # The 'New Starts/Raf' box.
    box_label_row = 0
    for r in range(header_row + 1, len(grid) + 1):
        if any(BOX_LABEL in _norm(v) for v in grid[r - 1]):
            box_label_row = r
            break
    if not box_label_row:
        raise BoardLayoutError(
            f"Couldn't find the {BOX_LABEL!r} label — the new-start "
            "terminations live in that box and would be silently skipped.")

    # Its own weekday header row, within a few rows of the label.
    box_header_row = 0
    box_days: list[tuple[int, int]] = []
    for r in range(box_label_row + 1, min(box_label_row + 6, len(grid)) + 1):
        found = [(c, WEEKDAYS[_norm(v)]) for c, v in enumerate(grid[r - 1], 1)
                 if _norm(v) in WEEKDAYS]
        if len(found) >= 3:
            box_header_row, box_days = r, found
            break
    if not box_header_row:
        raise BoardLayoutError(
            f"The {BOX_LABEL!r} box has no weekday header row (Monday…Saturday) "
            "within 5 rows of its label — can't date a new start's termination.")

    # A 'Roll Call' sub-header sits between the weekday names and the reps.
    box_first_row = box_header_row + 1
    if any("roll call" in _norm(v) for v in grid[box_first_row - 1]):
        box_first_row += 1

    box_name_col = next(
        (c for c, v in enumerate(grid[box_header_row - 1], 1)
         if _norm(v) == BOX_NAME_HEADER), name_col)

    # The roster's own day blocks, off row 1's 'MON'…'SUN' labels. Only the
    # labels to the RIGHT of the name column count: row 1 also carries the three
    # running-total sections, and those never use weekday names, but pinning the
    # search after the names keeps a future 'MON' summary header out of it.
    day_blocks = _blocks((c, DAY_LABELS[_norm(v)])
                         for c, v in enumerate(grid[0], 1)
                         if c > name_col and _norm(v) in DAY_LABELS)
    if len(day_blocks) < 5:
        raise BoardLayoutError(
            f"Only found {len(day_blocks)} weekday block(s) on row 1 "
            f"(MON…SUN, right of column {name_col}) — the roster's 'T' marks "
            "are dated by which block they land in, so they'd all be missed.")

    return Layout(header_row=header_row, name_col=name_col,
                  days_col=titles[COL_DAYS_WORKED],
                  term_col=titles[COL_TERM_DATE],
                  start_col=titles[COL_START_DATE],
                  box_label_row=box_label_row, box_header_row=box_header_row,
                  box_first_row=box_first_row, box_name_col=box_name_col,
                  box_days=tuple(sorted(box_days, key=lambda x: x[1])),
                  day_blocks=day_blocks,
                  box_blocks=_blocks((c, off) for c, off in box_days))


# -------------------------------------------------------------------- scan

def _fmt(d: dt.date | None) -> str:
    return "—" if d is None else f"{d.strftime('%a')} {d.month}/{d.day}"


def _marked_days(grid: list, row: int, lay: Layout) -> str:
    """The T marks of a row, named by their column headers, for a Check line."""
    bits = []
    for m in day_marks(grid, row, lay.day_blocks):
        cols = [str(_cell(grid, lay.header_row, c) or f"col {c}").strip()
                for c in m.marks]
        bits.append(f"{[k for k, v in WEEKDAYS.items() if v == m.offset][0].title()}"
                    f" ({', '.join(cols)})")
    return "; ".join(bits)


def _roster_t_row(grid: list, lay, r: int, name: str, marked: dt.date,
                  tab: str) -> Termination:
    """The termination a bare 'T' states, on the roster.

    With no Termination Date the '# Days Worked' cell is still counting from
    TODAY() and can't be read, so the day count is derived the way that column's
    own formula would: termination minus start, blank when there is no start.

    Split out because a flagged (mixed-day) row needs the very same row built
    without filing it — it becomes Check.proposed, the row a ✅ releases.
    """
    start = to_date(_cell(grid, r, lay.start_col))
    n = (marked - start).days if start else None
    return Termination(
        name=name, term_date=marked,
        days_worked=n if n is not None and 0 <= n <= 20000 else None,
        source="roster T", tab=tab, row=r)


def scan_grid(grid: list, tab: str,
              monday: dt.date) -> tuple[list[Termination], list[Check]]:
    """One week tab → the terminations it states, plus the rows it contradicts
    itself about. Board order for both."""
    lay = find_layout(grid)
    out: list[Termination] = []
    checks: list[Check] = []

    # 1) the roster. A filled Termination Date IS the termination; a bare 'T'
    #    anywhere in a day block is one too, and the block dates it.
    for r in lay.roster_rows:
        name = str(_cell(grid, r, lay.name_col) or "").strip()
        if not name:
            continue
        term = to_date(_cell(grid, r, lay.term_col))
        marks = day_marks(grid, r, lay.day_blocks)
        marked = monday + dt.timedelta(days=marks[0].offset) if marks else None

        if term is not None:
            # The date column wins — it is the only signal carrying a real day
            # count, and it is what Eve has always filed by. But if the T marks
            # point at a different day than the date does, say so: one of the
            # two was typed wrong and only she can tell which.
            if marked is not None and abs((term - marked).days) > 1:
                checks.append(Check(
                    name=name, tab=tab, row=r,
                    reason=(f"'Termination Date' says {_fmt(term)} but the T "
                            f"marks start {_fmt(marked)} — "
                            f"{_marked_days(grid, r, lay)}. Filed under "
                            f"{_fmt(term)}."),
                    marked_date=marked, board_date=term))
            out.append(Termination(
                name=name, term_date=term,
                days_worked=_roster_days(_cell(grid, r, lay.days_col),
                                         _cell(grid, r, lay.start_col)),
                source="roster", tab=tab, row=r))
            continue

        if not marks:
            continue
        first = marks[0]
        if first.conflicts:
            # A 'T' next to a real roll call or a non-zero metric on the SAME
            # day. Not filed and not dated — the whole point of the flag.
            shown = ", ".join(
                f"{str(_cell(grid, lay.header_row, c) or f'col {c}').strip()}={v}"
                for c, v in first.conflicts[:4])
            checks.append(Check(
                name=name, tab=tab, row=r,
                reason=(f"marked T on {_fmt(marked)} but the same day still "
                        f"reads {shown} — not filed, tell me which it is."),
                marked_date=marked, board_date=None,
                proposed=_roster_t_row(grid, lay, r, name, marked, tab)))
            continue

        out.append(_roster_t_row(grid, lay, r, name, marked, tab))

    # 2) the New Starts/Raf box — the FIRST weekday marked terminated. Its day
    #    columns get the same whole-block treatment as the roster's, so a mark
    #    typed one column off still lands on the right day.
    for r in range(lay.box_first_row, len(grid) + 1):
        name = str(_cell(grid, r, lay.box_name_col) or "").strip()
        if not name:
            continue
        box_marks = day_marks(grid, r, lay.box_blocks)
        hit = box_marks[0].offset if box_marks else None
        if hit is None:
            continue
        # A new start's week begins Monday, so the weekday offset of their first
        # 'Terminated' cell is how far into the week they got — which is both
        # the date and the day count, shifted by BOX_DAY_OFFSET (see above).
        off = hit + BOX_DAY_OFFSET
        out.append(Termination(
            name=name, term_date=monday + dt.timedelta(days=off),
            days_worked=off,
            source="new starts", tab=tab, row=r))
    return out, checks


def dedupe(rows: Iterable[Termination]) -> list[Termination]:
    """Collapse a rep who shows up in BOTH blocks on the same date (a new start
    who has already been promoted onto the roster). The roster wins — it carries
    the real start date, so its day count spans their whole tenure, not just
    this week."""
    best: dict[tuple, Termination] = {}
    for t in rows:
        prior = best.get(t.key)
        if prior is None or SOURCE_RANK.get(t.source, 9) < SOURCE_RANK.get(prior.source, 9):
            best[t.key] = t
    return sorted(best.values(), key=lambda t: (t.term_date, t.row))


def _scan_one(sh, title: str, today: dt.date,
              logfn) -> tuple[list[Termination], list[Check]]:
    ws = sh.worksheet(title)
    grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    m = WE_TAB_RE.match(_norm(title))
    sunday = _resolve_tab_date(int(m.group(1)), int(m.group(2)), today)
    monday = sunday - dt.timedelta(days=6)
    rows, checks = scan_grid(grid, title, monday)
    by = lambda s: sum(1 for t in rows if t.source == s)      # noqa: E731
    logfn(f"  {title!r} (Mon {monday.isoformat()} → Sun {sunday.isoformat()}): "
          f"{len(rows)} terminated ({by('roster')} roster date, "
          f"{by('roster T')} roster T, {by('new starts')} new starts)"
          + (f", {len(checks)} to check" if checks else ""))
    return rows, checks


# How far back a PREVIOUS week's tab is still allowed to contribute.
#
# The look-back exists for one reason: a new 'Sales Board WE <m>.<d>' tab is
# created every MONDAY, and the weekend's roll-call keeps being filled in on the
# OLD tab afterwards — so a rep marked Terminated on Monday, against Saturday,
# would otherwise never be filed by anyone.
#
# It is NOT a backfill. Taking the previous tab wholesale drags up terminations
# Eve entered late under a different date — the 8/3 catch-up batch put Jacob
# Ezernack and Alexander Delgado five and six days from what the board says —
# and the tracker's ±1 day match can't recognise those, so it would file them
# all over again. Four days covers the weekend an early-week run needs and
# nothing older.
LOOKBACK_DAYS = 4


@dataclass
class ScanResult:
    rows: list[Termination]
    title: str
    checks: list[Check]


def scan_full(today: dt.date, *, tab: str | None = None, back_weeks: int = 1,
              logfn=print) -> ScanResult:
    """Read the week tab covering `today`, plus the recent tail of the previous
    one(s). See LOOKBACK_DAYS. `tab` pins a single tab and turns the look-back
    off (backfill/testing).

    THE PREVIOUS TAB IS READ EVEN WHEN IT CAN NO LONGER CONTRIBUTE A ROW, and
    that is deliberate. A new week's tab is copied from the old one, so a rep
    terminated last Thursday arrives on Monday's tab already carrying 'T' in
    every day block from Monday on. Read alone, that reads as a brand-new
    Monday termination — Jaylen (Ash) Walker is 8/20 on WE 8.23 and would have
    been refiled as 8/24 off WE 8.30, four days apart, which is more than the
    tracker's ±1 day dedupe can see. So anyone the PREVIOUS tab already marked
    is dropped from THIS tab's T-derived rows. Rows with a real Termination
    Date are untouched by this: that column is filled per termination, not
    copied forward."""
    sh = open_by_key(SHEET_ID)
    title = pick_tab(sh, today, tab)
    rows, checks = _scan_one(sh, title, today, logfn)

    if tab is None and back_weeks > 0:
        cutoff = today - dt.timedelta(days=LOOKBACK_DAYS)
        tabs = week_tabs(sh, today)
        titles = [t for _d, t in tabs]
        if title in titles:
            i = titles.index(title)
            carried: set[str] = set()
            for sunday, prev in tabs[max(0, i - back_weeks):i]:
                prev_rows, prev_checks = _scan_one(sh, prev, today, logfn)
                carried |= {base_name(t.name) for t in prev_rows}
                carried |= {base_name(c.name) for c in prev_checks}
                if sunday < cutoff:
                    logfn(f"  {prev!r}: ends {sunday.isoformat()}, older than "
                          f"the {LOOKBACK_DAYS}-day window — read only to "
                          f"recognise carried-over T marks, nothing filed "
                          f"from it")
                    continue
                recent = [t for t in prev_rows if t.term_date >= cutoff]
                logfn(f"    {len(recent)} of them dated "
                      f"{cutoff.isoformat()} or later — the rest are last "
                      f"week's, already filed")
                rows += recent
                checks += prev_checks

            def carried_over(t: Termination) -> bool:
                return (t.tab == title and t.source == "roster T"
                        and base_name(t.name) in carried)

            stale = [t for t in rows if carried_over(t)]
            if stale:
                logfn(f"  {len(stale)} T-marked row(s) on {title!r} were "
                      f"already marked last week — carried over by the tab "
                      f"copy, not new:")
                for t in stale:
                    logfn(f"     {t.name} (would have been filed "
                          f"{t.term_date.isoformat()})")
                rows = [t for t in rows if not carried_over(t)]
            checks = [c for c in checks
                      if not (c.tab == title and base_name(c.name) in carried)]

    return ScanResult(dedupe(rows), title, dedupe_checks(checks))


def dedupe_checks(checks: Iterable[Check]) -> list[Check]:
    """One line per person per reason, oldest tab first."""
    best: dict[tuple, Check] = {}
    for c in checks:
        best.setdefault(c.key, c)
    return sorted(best.values(), key=lambda c: (c.name.lower(), c.reason))


def scan(today: dt.date, *, tab: str | None = None, back_weeks: int = 1,
         logfn=print) -> tuple[list[Termination], str]:
    """`scan_full` without the checks — the shape mobrium_list reads."""
    r = scan_full(today, tab=tab, back_weeks=back_weeks, logfn=logfn)
    return r.rows, r.title
