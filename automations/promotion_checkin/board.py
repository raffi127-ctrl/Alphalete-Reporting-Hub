"""Read the office Sales Board and return this week's promotable reps.

Label-anchored, never index-anchored: the roster block moves around, but the
column HEADERS ('Trainer', 'Field Status', 'Team', 'Leadership Status',
'Location') don't — so we find columns by header text, and the rep-name column
by the "WE m/d- m/d" week label that sits above it. See
[[feedback_no_hardcoded_columns]] / [[feedback_derive_sheet_positions]].
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from . import config as C

# Newest tab is the "most current week" — pick the largest date in
# "Sales Board WE M.D" (NOT "Energy Sales Board WE …", a different board/layout).
_WE_TAB = re.compile(r"^Sales Board WE (\d+)\.(\d+)\s*$")
# Trailing tenure/status markers on a name we strip for the recognition sheet:
# "(Wk 2)", "(Wk 3)", "(NC)", "(RT)". An internal nickname like "(Ivette)" stays.
_NAME_MARKER = re.compile(r"\s*\((?:wk\s*\d+|nc|rt)\)\s*$", re.I)
_WEEK_LABEL = re.compile(r"we\s*\d", re.I)
# Rows in the roster column that are totals / headers, not people.
_JUNK_NAME = re.compile(r"^(we\s|apps|total|active|leader|#|x$|v$)", re.I)


@dataclass
class Rep:
    name: str            # cleaned (tenure markers stripped), as it goes to the sheet
    trainer: str
    field: str           # "2nd Wk" / "5th wk+" / "RT" — tenure, shown for context
    team: str
    level: str           # current Leadership Status: Entry Level / Level 1 / ...
    location: str

    @property
    def promotable(self) -> bool:
        return self.level in C.LADDER

    @property
    def next_level(self):
        return C.LADDER.get(self.level, (None, None))[0]

    @property
    def recognition(self):
        """The Recognition-column string for a one-level-up promotion."""
        return C.LADDER.get(self.level, (None, None))[1]


def _clean_name(raw: str) -> str:
    return _NAME_MARKER.sub("", (raw or "").strip()).strip()


def _newest_board_year(month: int) -> int:
    """The tab labels carry no year; assume the current reporting year, but if
    that lands in the future (e.g. a Jan tab read in Dec) fall back a year."""
    today = dt.date.today()
    yr = today.year
    if dt.date(yr, month, 1) > today + dt.timedelta(days=60):
        yr -= 1
    return yr


def newest_board_tab(sh):
    """The Worksheet for the most-recent 'Sales Board WE' week."""
    best = None
    for w in sh.worksheets():
        m = _WE_TAB.match(w.title)
        if not m:
            continue
        mo, d = int(m.group(1)), int(m.group(2))
        key = dt.date(_newest_board_year(mo), mo, d)
        if best is None or key > best[0]:
            best = (key, w)
    if best is None:
        raise RuntimeError("No 'Sales Board WE M.D' tab found on the board sheet.")
    return best[1]


def _find_columns(grid):
    """Return (header_row_index, {field: col_index}, name_col_index)."""
    wanted = {"trainer": "Trainer", "field": "Field Status", "team": "Team",
              "level": "Leadership Status", "location": "Location"}
    for i, row in enumerate(grid[:8]):
        lower = [(c or "").strip().lower() for c in row]
        if "trainer" not in lower:
            continue
        cols = {}
        for key, label in wanted.items():
            lab = label.lower()
            j = next((k for k, v in enumerate(lower)
                      if v == lab or v.startswith(lab)), None)
            if j is not None:
                cols[key] = j
        if "trainer" not in cols or "level" not in cols:
            continue
        # Rep-name column: the one whose sub-header (next row) is the "WE m/d-"
        # week label. Fall back to column C (index 2), the board's fixed roster col.
        sub = grid[i + 1] if i + 1 < len(grid) else []
        name_col = next((k for k, v in enumerate(sub)
                         if _WEEK_LABEL.match((v or "").strip())), 2)
        return i, cols, name_col
    raise RuntimeError("Couldn't find the 'Trainer'/'Leadership Status' header row.")


def load_board(sheet_id: str = None):
    """Return (tab_title, week_label, [Rep]) for the newest board week.

    `week_label` is the human "WE 8.2" style tag from the tab title.
    """
    from automations.recruiting_report import fill
    sheet_id = sheet_id or C.BOARD_SHEET_ID
    sh = fill._client().open_by_key(sheet_id)
    ws = newest_board_tab(sh)
    grid = ws.get_all_values()
    hdr_i, cols, name_col = _find_columns(grid)

    def cell(row, key):
        j = cols.get(key)
        return (row[j].strip() if (j is not None and j < len(row)) else "")

    reps = []
    for row in grid[hdr_i + 2:]:
        raw = row[name_col].strip() if name_col < len(row) else ""
        if not raw or _JUNK_NAME.match(raw):
            continue
        level = cell(row, "level")
        if level not in C.LADDER and level != C.TOP_LEVEL:
            continue                       # not a real leadership-status row
        reps.append(Rep(name=_clean_name(raw), trainer=cell(row, "trainer"),
                        field=cell(row, "field"), team=cell(row, "team"),
                        level=level, location=cell(row, "location")))
    week = ws.title.replace("Sales Board ", "")
    return ws.title, week, reps


def eligible(reps):
    """Only reps who can still be promoted (below the top of the ladder)."""
    return [r for r in reps if r.promotable]


def by_team(reps):
    """Group -> {team: [Rep]} preserving first-seen team order."""
    groups = {}
    for r in reps:
        groups.setdefault(r.team or "Team", []).append(r)
    return groups
