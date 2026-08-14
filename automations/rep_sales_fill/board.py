"""Locate the rep row and the day's metric cells on the Sales Board -- by label.

Everything here is found by reading the sheet, never by a remembered index:
the week tab drifts columns constantly (the same board carried Field Status in
col CG one week and BX another), and the day blocks shift whenever a column is
inserted. Rows move too -- the live board gets re-sorted through the morning
(alphabetical at 07:34, by production later), so a row number read at 07:15 is
wrong by 07:40. Look the rep up every time.

THE APPS CELL IS A FORMULA and is never written:
  =ARRAYFORMULA(IFS(... , AY>=0, (AY+BA+BB+BC)))
which also means the day's STATUS ('X' didn't work, 'T' terminated, 'RT' road
trip, 'CR', 'F', 'L', 'STF', 'ATMO') is typed into the SAME cells as the sales
numbers. Writing a count over a status letter would erase the roll-call record,
so a day whose cells carry a status is reported and skipped, never overwritten.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

NAME_COL = 3                     # col C, the rep list
DAY_ROW, SUB_ROW = 1, 3          # row 1 = MON/TUES/..., row 3 = Apps/Int/...
METRICS = ("Int", "Int Up", "DTV", "NL")

# The board's day banner -> the weekday names the crosstab uses.
DAY_LABELS = {"MON": "Monday", "TUES": "Tuesday", "WED": "Wednesday",
              "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday",
              "SUN": "Sunday"}

# A day cell holding one of these is roll-call state, not a sale count.
STATUS_WORDS = {"X", "T", "RT", "CR", "F", "L", "STF", "ATMO", "OFF"}


def cell(grid, r: int, c: int) -> str:
    """1-based, tolerant of ragged rows (get_all_values truncates)."""
    if 1 <= r <= len(grid):
        row = grid[r - 1]
        if 1 <= c <= len(row):
            return str(row[c - 1] or "")
    return ""


def _norm_name(s: str) -> str:
    """'Jaylen (Ash) Walker (Wk 2)' -> 'jaylen walker'. The board decorates
    names with week/status suffixes that Tableau never carries."""
    t = re.sub(r"\(.*?\)", " ", str(s or ""))
    return " ".join(t.lower().split())


def last_rep_row(grid) -> int:
    """The roster ends at the col-C 'TOTALS' row. Below it live a leaders
    table, a notes block and a new-starts list that also put names in col C --
    reading past TOTALS once inflated a 64-rep roster to 177."""
    for r in range(SUB_ROW + 1, len(grid) + 1):
        if cell(grid, r, NAME_COL).strip().upper() == "TOTALS":
            return r - 1
    return len(grid)


def find_rep_row(grid, rep: str) -> Tuple[Optional[int], str]:
    """(row, note). Exact-ish match first, then a both-tokens match so
    'Andrew Sanborn' still finds 'Andrew Sanborn (Wk 2)'. Two matches is a
    real question for a human, so it returns None rather than guessing."""
    want = _norm_name(rep)
    last = last_rep_row(grid)
    rows = {r: _norm_name(cell(grid, r, NAME_COL))
            for r in range(SUB_ROW + 1, last + 1)
            if cell(grid, r, NAME_COL).strip()}

    exact = [r for r, n in rows.items() if n == want]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, f"{rep!r} matches {len(exact)} rows on the board"

    toks = set(want.split())
    part = [r for r, n in rows.items() if toks and toks <= set(n.split())]
    if len(part) == 1:
        return part[0], f"matched on name tokens: {cell(grid, part[0], NAME_COL).strip()!r}"
    if len(part) > 1:
        names = ", ".join(sorted(cell(grid, r, NAME_COL).strip() for r in part))
        return None, f"{rep!r} could be any of: {names}"
    return None, (f"{rep!r} is on no row of this week's board -- add them to the "
                  "roster first, or check the spelling against col C")


def day_blocks(grid) -> Dict[str, Dict[str, int]]:
    """{weekday: {metric: column}} for every day block on the tab.

    The banner cell (MON) sits over the block's Apps column; the sub-headers
    (Apps/Int/Int Up/DTV/NL/EN/Cx/Roll Call) run to its right until the next
    banner. Both are read live.
    """
    width = max(len(r) for r in grid[:SUB_ROW]) if grid else 0
    starts = []
    for c in range(1, width + 1):
        lab = cell(grid, DAY_ROW, c).strip().upper()
        if lab in DAY_LABELS:
            starts.append((c, DAY_LABELS[lab]))

    out: Dict[str, Dict[str, int]] = {}
    for i, (start, day) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else width
        cols: Dict[str, int] = {}
        for c in range(start, end + 1):
            head = " ".join(cell(grid, SUB_ROW, c).split())
            for m in METRICS:
                if head.lower() == m.lower():
                    cols[m] = c
        if cols:
            out[day] = cols
    return out


def is_status(value: str) -> bool:
    return value.strip().upper() in STATUS_WORDS


def plan_day(grid, row: int, cols: Dict[str, int], wanted: Dict[str, int],
             overwrite: bool = False) -> Tuple[list, list]:
    """(writes, notes) for ONE day.

    writes: [(metric, col, current, new)] -- only cells that actually change.
    A metric Tableau reports as 0 is written as blank, not '0': that is how the
    board reads elsewhere (a blank day cell is 'no sale', a literal 0 is a
    rolled zero the Zero Streak callout counts).

    A DAY THAT ALREADY CARRIES ANYTHING IS LEFT ALONE (Eve 2026-08-14). The
    board is edited by hand as well as by the fills, and a day already filled
    may have been corrected by a person -- so a disagreement is REPORTED, never
    silently reverted to Tableau. This module's job is the days nobody has
    filled yet. `overwrite=True` is the deliberate escape hatch for repairing a
    day you know is wrong.

    "Carries anything" is judged per DAY, not per cell, because the four
    measures are one reading: 1 Int + 1 DTV is somebody's coding of the same
    three units Tableau splits as 1 Int + 1 Int Up + 1 NL, and fixing only the
    blank cells of that day would ADD sales rather than re-split them.
    """
    writes, notes = [], []
    current = {m: cell(grid, row, c).strip() for m, c in cols.items()}

    status = {m: v for m, v in current.items() if is_status(v)}
    if status:
        notes.append("day carries roll-call status "
                     + ", ".join(f"{m}={v!r}" for m, v in sorted(status.items()))
                     + " -- left alone")
        return [], notes

    filled = {m: v for m, v in current.items() if v}
    if filled and not overwrite:
        want_s = {m: (str(wanted.get(m, 0)) if wanted.get(m, 0) else "")
                  for m in cols}
        if {m: v for m, v in want_s.items() if v} != filled:
            notes.append(
                "already filled ["
                + ", ".join(f"{m} {v}" for m, v in sorted(filled.items()))
                + "] but Tableau says ["
                + ", ".join(f"{m} {v}" for m, v in sorted(want_s.items()) if v)
                + "] -- LEFT AS IS (may be a hand correction; --overwrite to force)")
        return [], notes

    for metric, col in sorted(cols.items()):
        cur = current[metric]
        new = wanted.get(metric, 0)
        new_s = str(new) if new else ""
        if cur == new_s:
            continue
        if cur and not cur.isdigit():
            notes.append(f"{metric} holds {cur!r}, which is not a count -- left alone")
            continue
        writes.append((metric, col, cur, new_s))
    return writes, notes
