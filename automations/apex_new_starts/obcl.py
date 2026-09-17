"""Tick 'Added to APEX' on the week's OBCL tab.

Megan, 2026-09-17: "they have the sheet open and we automate the run to mark
the OBCL on their machine."

The filling happens in a browser and a bookmarklet cannot reach Google Sheets,
so the run's outcome comes back the way the setup went out: through the
clipboard, on the same machine. This module is the half that writes.

TWO STATES, because they mean different things:

    found  -> the cell goes GREEN.  We located them on Apex's Pending tab.
    added  -> the checkbox is TICKED. All three pages saved and Apex flipped
              them to Active.

Nothing else on the tab is touched. The OBCL is hand-maintained by the
recruiting team: this writes one column, on rows it can match by name, and
leaves every other cell exactly as it found it.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

from automations.blueink_docs import config as C
from automations.recruiting_report.fill import open_by_key

# By LABEL, never by position — the OBCL gains columns regularly (this one was
# added the week it was asked for). See the no-hardcoded-columns rule.
COL_FIRST = "name"
COL_LAST = "last name"
COL_APEX = "added to apex"

GREEN = {"red": 0.82, "green": 0.94, "blue": 0.83}   # the sheet's own pass-green


def _fold(text: str) -> str:
    """'Le'derius ' -> 'lederius'. Accents, punctuation and case all go."""
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", raw.lower())


def _key(first: str, last: str) -> str:
    return f"{_fold(first)}|{_fold(last)}"


def split_name(full: str) -> Tuple[str, str]:
    """'Emily Flores Castaneda' -> ('Emily', 'Flores Castaneda').

    The board carries one name; the OBCL keeps first and last apart. Everything
    after the first word is the surname, which is how the sheet holds the
    two-word ones.
    """
    parts = str(full or "").split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def tab_for(week_start: dt.date, titles: Iterable[str]) -> Optional[str]:
    """The dated OBCL tab whose label falls inside this board week."""
    best = None
    for title in titles:
        m = re.match(r"^\s*" + re.escape(C.DATED_TAB_PREFIX) +
                     r"\s+(\d{1,2})\.(\d{1,2})\s*$", title, re.I)
        if not m:
            continue
        month, day = int(m.group(1)), int(m.group(2))
        for year in (week_start.year, week_start.year - 1):
            try:
                when = dt.date(year, month, day)
            except ValueError:
                continue
            if week_start <= when <= week_start + dt.timedelta(days=6):
                if best is None or when < best[0]:
                    best = (when, title)
    return best[1] if best else None


def _layout(grid: List[List[str]]) -> Tuple[int, Dict[str, int]]:
    """(header row index, {label: column index}) — found by reading the labels.

    The header is not row 1: row 1 carries the week's date. So the header is
    whichever row actually holds the labels we need.
    """
    for r, row in enumerate(grid[:12]):
        folded = {_fold(c): i for i, c in enumerate(row) if str(c).strip()}
        if all(_fold(k) in folded for k in (COL_FIRST, COL_LAST, COL_APEX)):
            return r, {k: folded[_fold(k)]
                       for k in (COL_FIRST, COL_LAST, COL_APEX)}
    raise RuntimeError(
        "The OBCL tab has no 'Name' / 'Last Name' / 'Added to APEX' header row. "
        "If the column was renamed, rename it here too — this never guesses at "
        "a position.")


def plan(grid: List[List[str]], found: Iterable[str], added: Iterable[str]):
    """What would be written, without writing it.

    Returns (ticks, greens, unmatched) — ticks and greens are 1-based sheet
    row numbers, unmatched is the names no row carried.
    """
    hdr, cols = _layout(grid)
    rows: Dict[str, int] = {}
    for r in range(hdr + 1, len(grid)):
        row = grid[r]
        if len(row) <= max(cols.values()):
            continue
        k = _key(row[cols[COL_FIRST]], row[cols[COL_LAST]])
        if k != "|":
            rows.setdefault(k, r + 1)          # first match wins; 1-based

    added_set = list(added)
    # Anybody added was necessarily found, so a tick implies the green too.
    want_green = list(found) + added_set
    ticks, greens, unmatched = [], [], []
    for name in added_set:
        r = rows.get(_key(*split_name(name)))
        if r:
            ticks.append(r)
        else:
            unmatched.append(name)
    for name in want_green:
        r = rows.get(_key(*split_name(name)))
        if r and r not in greens:
            greens.append(r)
        elif not r and name not in unmatched:
            unmatched.append(name)
    return sorted(ticks), sorted(greens), unmatched


def mark(week_start: dt.date, found: Iterable[str], added: Iterable[str],
         *, dry_run: bool = False, log=print) -> int:
    """Green for found, ticked for added. Returns how many rows were ticked."""
    sh = open_by_key(C.SHEET_ID)
    title = tab_for(week_start, [ws.title for ws in sh.worksheets()])
    if not title:
        log(f"  ❌ No dated OBCL tab for the week of {week_start:%m/%d/%Y}.")
        return 0
    ws = sh.worksheet(title)
    grid = ws.get_all_values()
    hdr, cols = _layout(grid)
    ticks, greens, unmatched = plan(grid, found, added)
    col = cols[COL_APEX] + 1                   # gspread is 1-based

    log(f"  {title}: {len(ticks)} to tick, {len(greens)} to colour"
        + (f", {len(unmatched)} not on the tab" if unmatched else ""))
    for name in unmatched:
        log(f"     ⚠️  no row for {name}")
    if dry_run:
        log("  (dry run — nothing written)")
        return 0

    # One update per contiguous run rather than per cell: a per-cell loop is
    # what 429s the next report on this account (see the Sheets write-quota
    # note). These are single-column writes, so a range per row-block is fine.
    if ticks:
        ws.batch_update([{"range": f"{_a1(col)}{r}", "values": [[True]]}
                         for r in ticks])
    if greens:
        ws.format([f"{_a1(col)}{r}" for r in greens],
                  {"backgroundColor": GREEN})
    return len(ticks)


def _a1(col: int) -> str:
    """1 -> A, 23 -> W."""
    out = ""
    while col:
        col, rem = divmod(col - 1, 26)
        out = chr(65 + rem) + out
    return out
