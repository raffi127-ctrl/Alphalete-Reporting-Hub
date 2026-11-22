"""Tick 'Added to APEX' on the week's OBCL tab.

Megan, 2026-09-17: "they have the sheet open and we automate the run to mark
the OBCL on their machine."

The filling happens in a browser and a bookmarklet cannot reach Google Sheets,
so the run's outcome comes back the way the setup went out: through the
clipboard, on the same machine. This module is the half that writes.

ONE STATE, shown two ways. The column is called "Added to APEX": all three
pages saved and Apex flipped them to Active. Those rows get the checkbox AND
the cell goes green (Megan, 2026-09-17: "it's now checked but not green. We can
just make it green too please").

There was a green for "found" as well, once, and it earned its way out: a
colour meaning "we got as far as attempting them" is not something anybody
would look at, and it had drifted to include people the run could not find at
all. Green means the same as the tick now. Whoever did not make it is named in
the panel, which is where a person actually looks.

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
from automations.shared import obcl_tabs
from automations.recruiting_report.fill import open_by_key

# By LABEL, never by position — the OBCL gains columns regularly (this one was
# added the week it was asked for). See the no-hardcoded-columns rule.
COL_FIRST = "name"
COL_LAST = "last name"
COL_APEX = "added to apex"

GREEN = {"red": 0.71, "green": 0.87, "blue": 0.66}   # the sheet's own pass-green


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
    """The dated OBCL tab whose label falls inside this board week.

    Parse shared with Blue Ink, headshots and the follow-up report
    (automations/shared/obcl_tabs); the week window and "earliest wins" are
    this caller's own rule.
    """
    return obcl_tabs.in_week(titles, week_start)


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


def plan(grid: List[List[str]], added: Iterable[str]):
    """What would be written, without writing it.

    Returns (ticks, unmatched) — ticks are 1-based sheet row numbers,
    unmatched is the names no row carried.
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

    ticks, unmatched = [], []
    for name in added:
        r = rows.get(_key(*split_name(name)))
        if r and r not in ticks:
            ticks.append(r)
        elif not r:
            unmatched.append(name)
    return sorted(ticks), unmatched


def _week_tab(week_start: dt.date, office_key: str, log):
    """The tab to tick, on the board that office actually reads.

    NO FLAG DAY, the same rule as icd_onboarding.sheet.board_for: an office
    with a book of its own is written there, one without is left exactly as
    it was. Without this the tick went to Raf's All in One whatever the
    office read -- measured 2026-11-22, 0 of 66 and 0 of 31 on his own book
    while the column was being ticked on the stacked tab next door. That is
    the third writer this month pointed at the board nobody reads any more.
    """
    if office_key:
        try:
            from automations.icd_onboarding import sheet as S
            own = S.board_for(office_key, week_start, create=False)
            if own is not None:
                return own
        except Exception as e:                 # noqa: BLE001
            # Never lose the tick over the lookup: say so and fall back.
            log(f"  (could not open {office_key}'s own board: "
                f"{type(e).__name__}; using the stacked tab)")
    sh = open_by_key(C.SHEET_ID)
    title = tab_for(week_start, [ws.title for ws in sh.worksheets()])
    if not title:
        log(f"  ❌ No dated OBCL tab for the week of {week_start:%m/%d/%Y}.")
        return None
    return sh.worksheet(title)


def mark(week_start: dt.date, added: Iterable[str],
         *, dry_run: bool = False, log=print, office_key: str = "") -> int:
    """Tick 'Added to APEX'. Returns how many rows were ticked."""
    ws = _week_tab(week_start, office_key, log)
    if ws is None:
        return 0
    title = getattr(ws, "title", "the OBCL tab")
    grid = ws.get_all_values()
    hdr, cols = _layout(grid)
    ticks, unmatched = plan(grid, added)
    col = cols[COL_APEX] + 1                   # gspread is 1-based

    log(f"  {title}: {len(ticks)} to tick"
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
        # Same rows, green as well: the tick is easy to miss down a column of
        # empty boxes.
        ws.format([f"{_a1(col)}{r}" for r in ticks],
                  {"backgroundColor": GREEN})
    return len(ticks)


def _a1(col: int) -> str:
    """1 -> A, 23 -> W."""
    out = ""
    while col:
        col, rem = divmod(col - 1, 26)
        out = chr(65 + rem) + out
    return out
