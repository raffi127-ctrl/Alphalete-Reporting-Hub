"""Read TERMINATED reps off the Alphalete SALES BOARD 2025.

Source: workbook 'Alphalete SALES BOARD 2025'
(1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc), one tab per week named
'Sales Board WE <M>.<D>' where <M>.<D> is the week's SUNDAY (so 'WE 8.9' is
Mon 8/3 → Sun 8/9).

A tab carries TWO populations, and they mark a termination in TWO DIFFERENT
WAYS. Both have to be read or half the terminations are missed — the tenured
roster never shows the word 'Terminated' anywhere, and the new starts never
get a Termination Date:

  1. THE ROSTER (top block, from the header row down to the 'New Starts/Raf'
     label). Terminated = the per-rep 'Termination Date' column is filled in.
     '# Days Worked' sits beside it and is a live formula
     (=IF(<term>=0, TODAY()-<start>, <term>-<start>)) — we read its VALUE, we
     never recompute it, so the tracker always agrees with the board.
     Verified 2026-08-07 against the tracker: Adriannah Reyes (Wk 3) 16 days /
     8-5, Emmanuel Nieto 4 / 8-4, Jade Sapp (Wk 2) 7 / 8-3.

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

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}

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
    source: str                  # 'roster' | 'new starts'
    tab: str
    row: int                     # 1-indexed row on the tab, for the audit trail

    @property
    def key(self) -> tuple[str, dt.date]:
        """Dedupe identity. A rep CAN legitimately appear twice with two
        different dates (rehired then let go again — Myra Singleton 7/31 and
        8/3 both sit in the tracker), so the date is part of the key."""
        return (norm_name(self.name), self.term_date)


def norm_name(s: str) -> str:
    """Fold a name for comparison only — never for writing. Handles the
    non-breaking spaces and stray tabs that pasted names carry
    ('Gabriel\\xa0 Armando Rivera', 'Christian\\tWilliams')."""
    return " ".join(str(s or "").replace("\xa0", " ").replace("\t", " ").split()).lower()


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

    @property
    def roster_rows(self) -> range:
        return range(self.header_row + 1, self.box_label_row)


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

    return Layout(header_row=header_row, name_col=name_col,
                  days_col=titles[COL_DAYS_WORKED],
                  term_col=titles[COL_TERM_DATE],
                  start_col=titles[COL_START_DATE],
                  box_label_row=box_label_row, box_header_row=box_header_row,
                  box_first_row=box_first_row, box_name_col=box_name_col,
                  box_days=tuple(sorted(box_days, key=lambda x: x[1])))


# -------------------------------------------------------------------- scan

def scan_grid(grid: list, tab: str, monday: dt.date) -> list[Termination]:
    """Both blocks of one week tab → terminations, in board order."""
    lay = find_layout(grid)
    out: list[Termination] = []

    # 1) the roster — a filled Termination Date IS the termination.
    for r in lay.roster_rows:
        name = str(_cell(grid, r, lay.name_col) or "").strip()
        term = to_date(_cell(grid, r, lay.term_col))
        if not name or term is None:
            continue
        out.append(Termination(
            name=name, term_date=term,
            days_worked=_roster_days(_cell(grid, r, lay.days_col),
                                     _cell(grid, r, lay.start_col)),
            source="roster", tab=tab, row=r))

    # 2) the New Starts/Raf box — the FIRST 'Terminated' weekday.
    for r in range(lay.box_first_row, len(grid) + 1):
        name = str(_cell(grid, r, lay.box_name_col) or "").strip()
        if not name:
            continue
        hit = next((off for col, off in lay.box_days
                    if _norm(_cell(grid, r, col)) == TERMINATED), None)
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
    return out


def dedupe(rows: Iterable[Termination]) -> list[Termination]:
    """Collapse a rep who shows up in BOTH blocks on the same date (a new start
    who has already been promoted onto the roster). The roster wins — it carries
    the real start date, so its day count spans their whole tenure, not just
    this week."""
    best: dict[tuple, Termination] = {}
    for t in rows:
        prior = best.get(t.key)
        if prior is None or (prior.source != "roster" and t.source == "roster"):
            best[t.key] = t
    return sorted(best.values(), key=lambda t: (t.term_date, t.row))


def _scan_one(sh, title: str, today: dt.date, logfn) -> list[Termination]:
    ws = sh.worksheet(title)
    grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    m = WE_TAB_RE.match(_norm(title))
    sunday = _resolve_tab_date(int(m.group(1)), int(m.group(2)), today)
    monday = sunday - dt.timedelta(days=6)
    rows = scan_grid(grid, title, monday)
    logfn(f"  {title!r} (Mon {monday.isoformat()} → Sun {sunday.isoformat()}): "
          f"{len(rows)} terminated "
          f"({sum(1 for t in rows if t.source == 'roster')} roster, "
          f"{sum(1 for t in rows if t.source == 'new starts')} new starts)")
    return rows


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


def scan(today: dt.date, *, tab: str | None = None, back_weeks: int = 1,
         logfn=print) -> tuple[list[Termination], str]:
    """Read the week tab covering `today`, plus the recent tail of the previous
    one(s). See LOOKBACK_DAYS. `tab` pins a single tab and turns the look-back
    off (backfill/testing)."""
    sh = open_by_key(SHEET_ID)
    title = pick_tab(sh, today, tab)
    rows = _scan_one(sh, title, today, logfn)

    if tab is None and back_weeks > 0:
        cutoff = today - dt.timedelta(days=LOOKBACK_DAYS)
        tabs = week_tabs(sh, today)
        titles = [t for _d, t in tabs]
        if title in titles:
            i = titles.index(title)
            for sunday, prev in tabs[max(0, i - back_weeks):i]:
                # Its newest possible termination is its own Sunday. If even
                # that is older than the cutoff the tab can't contribute — skip
                # the read rather than pay for it.
                if sunday < cutoff:
                    logfn(f"  {prev!r}: ends {sunday.isoformat()}, older than "
                          f"the {LOOKBACK_DAYS}-day window — skipped")
                    continue
                recent = [t for t in _scan_one(sh, prev, today, logfn)
                          if t.term_date >= cutoff]
                logfn(f"    {len(recent)} of them dated "
                      f"{cutoff.isoformat()} or later — the rest are last "
                      f"week's, already filed")
                rows += recent

    rows = dedupe(rows)
    return rows, title
