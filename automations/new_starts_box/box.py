"""Reading the 'New Starts/Raf' box off a Sales Board tab.

THE BOX IS NOT AT A FIXED ROW. It sits under the roster, under the leaders
table and under the notes block, so it lands wherever this week's roster
happens to end -- r178 on WE 9.13, r186 on WE 9.6. It is found by its TITLE in
col C, and its columns by the header row directly beneath that title.

Its header row is its OWN: 'Classroom | Trainers | Email | Ran Orientation |
... | Location | ... | Team'. Those labels have nothing to do with the roster's
row-1 labels far above, which is why the box is read with its own header row
and the roster with row 1.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from automations.new_starts_box import config as C
from automations.new_starts_box.names import norm

NAME_COL = 3            # col C -- the only fixed thing on the board, and the
                        # same anchor rep_sales_fill.board uses for the roster.


def cell(grid, r: int, c: int) -> str:
    """1-based, tolerant of the ragged rows get_all_values returns."""
    if 1 <= r <= len(grid):
        row = grid[r - 1]
        if 1 <= c <= len(row):
            return str(row[c - 1] or "")
    return ""


def width(grid) -> int:
    return max((len(r) for r in grid), default=0)


def find_box(grid) -> Tuple[int, Dict[str, int]]:
    """(header row, {label: column}) for the New Starts box.

    Raises with the title it looked for -- a renamed box must stop the run, not
    fill an empty box with nothing.
    """
    want = norm(C.BOX_TITLE)
    title_row = None
    for r in range(1, len(grid) + 1):
        if norm(cell(grid, r, NAME_COL)) == want:
            title_row = r
            break
    if title_row is None:
        raise RuntimeError(
            "no %r row in col C of this tab -- the box was renamed or moved. "
            "Nothing was written." % C.BOX_TITLE)

    hrow = title_row + 1
    labels = {" ".join(cell(grid, hrow, c).split()): c
              for c in range(1, width(grid) + 1)
              if cell(grid, hrow, c).strip()}
    missing = [lab for lab in (C.BOX_NAME_LABEL, C.BOX_TRAINER_LABEL,
                               C.BOX_LOCATION_LABEL, C.BOX_TEAM_LABEL)
               if lab not in labels]
    if missing:
        raise RuntimeError(
            "the %r header row (row %d) has no %s column -- found %s. Nothing "
            "was written." % (C.BOX_TITLE, hrow, ", ".join(missing),
                              ", ".join(sorted(labels)) or "nothing"))
    return hrow, labels


def entries(grid, header_row: int) -> List[Tuple[int, str]]:
    """[(row, name)] for every new start listed under the box's header.

    Runs to the END of the grid on purpose: the box is the last thing on the
    tab and its blank rows are gaps people leave, not a terminator (WE 9.6 has
    an empty row between the header and the first name).
    """
    out = []
    for r in range(header_row + 1, len(grid) + 1):
        name = cell(grid, r, NAME_COL).strip()
        if name:
            out.append((r, name))
    return out


def last_roster_row(grid) -> int:
    """The roster ends at col C 'TOTALS'; everything below is other blocks."""
    for r in range(4, len(grid) + 1):
        if cell(grid, r, NAME_COL).strip().upper() == "TOTALS":
            return r - 1
    return len(grid)


def roster_teams(grid) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """([(rep name, team)], note). Team comes from the ROSTER's row-1 'Team'
    column (col CI this week), not from the box's own 'Team' header."""
    row1 = {" ".join(cell(grid, 1, c).split()): c
            for c in range(1, width(grid) + 1) if cell(grid, 1, c).strip()}
    col = row1.get(C.ROSTER_TEAM_LABEL)
    if not col:
        return [], ("no %r column in row 1 -- every Team cell is left blank"
                    % C.ROSTER_TEAM_LABEL)
    out = []
    for r in range(4, last_roster_row(grid) + 1):
        name = cell(grid, r, NAME_COL).strip()
        team = cell(grid, r, col).strip()
        if name and team:
            out.append((name, team))
    return out, None


def a1(row: int, col: int) -> str:
    letters, c = "", col
    while c > 0:
        c, rem = divmod(c - 1, 26)
        letters = chr(65 + rem) + letters
    return "%s%d" % (letters, row)
