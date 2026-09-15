"""Where the weekly board picture sits on a Focus Report office tab.

The picture is an =IMAGE() formula, and =IMAGE draws INSIDE its cell, so it
needs a block of merged cells big enough to be read. That block goes UNDER
everything already on the tab — the Monday fills write the rows above it —
and starts at THE CURRENT WEEK'S COLUMN (Eve 2026-09-14: "sobre la columna de
la semana corriente", CP for WE 9/13), running right over the still-empty
future weeks. Next week it moves one column right, so it always sits under the
week a reader has scrolled to; old weeks' columns are often hidden on these
tabs, which is exactly why a block parked at column C was invisible.

Found by a column-A marker, never by a row number (CLAUDE.md): the first run
puts the marker a couple of rows under the last used row; every later run
finds the marker, takes last week's block apart and builds this week's on the
same row, so the block never walks DOWN the tab.

Never left of the frozen columns: Google refuses a merge that crosses the
frozen edge (A:B are frozen on the office tabs).
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

MARKER = "WEEKLY KNOCKS BOARD"
GAP_ROWS = 2                 # blank rows between the tab's content and the block
DISPLAY_W = 1200             # target on-screen width of the picture, px
DEFAULT_COL_PX = 100         # Sheets' default column width
DEFAULT_ROW_PX = 21          # Sheets' default row height


def _norm(s) -> str:
    return " ".join(str(s or "").split()).upper()


def find_marker(col_a: Sequence[str]) -> Optional[int]:
    """1-indexed row of the marker in column A, or None."""
    return next((i for i, v in enumerate(col_a, 1) if _norm(v) == MARKER), None)


def last_used_row(values: Sequence[Sequence[str]]) -> int:
    """Last row with anything in ANY column (0 for an empty tab)."""
    return max((i for i, r in enumerate(values, 1)
                if any(str(x).strip() for x in r)), default=0)


def start_column(week_col: int, frozen_cols: int) -> int:
    """The block's first column: the current week's, but never inside the
    frozen columns."""
    return max(week_col, frozen_cols + 1)


def block(col_px: Sequence[Optional[int]], row_px: Sequence[Optional[int]],
          start_col: int, start_row: int, img_w: int, img_h: int,
          display_w: int = DISPLAY_W,
          max_col: Optional[int] = None) -> Tuple[int, int]:
    """(end_col, end_row), 1-indexed and inclusive, of the smallest block
    starting at (start_row, start_col) that is at least `display_w` px wide and
    tall enough for the picture at that width (=IMAGE mode 1 keeps the aspect,
    so a block slightly larger than the picture just leaves a margin).

    `max_col` stops the block at the tab's last column — near the end of the
    template's weeks the picture gets narrower instead of the tab growing."""
    def px(seq, i, default):
        v = seq[i - 1] if 0 < i <= len(seq) else None
        return v if v else default

    col, width = start_col, 0
    while True:
        width += px(col_px, col, DEFAULT_COL_PX)
        if width >= display_w or (max_col is not None and col >= max_col):
            break
        col += 1
    need_h = width * img_h / max(img_w, 1)
    row, height = start_row, 0
    while True:
        height += px(row_px, row, DEFAULT_ROW_PX)
        if height >= need_h:
            break
        row += 1
    return col, row


def _inside(r: int, c: int, merge: dict) -> bool:
    return (merge["startRowIndex"] < r <= merge["endRowIndex"]
            and merge["startColumnIndex"] < c <= merge["endColumnIndex"])


def area_is_empty(values: Sequence[Sequence[str]], r1: int, r2: int,
                  c1: int, c2: int, ignore: Sequence[dict] = ()) -> bool:
    """True when no cell in rows r1..r2 x cols c1..c2 (1-indexed, inclusive)
    holds anything, not counting cells inside `ignore` merges (last week's
    block, which is ours and comes apart first)."""
    for r in range(r1, min(r2, len(values)) + 1):
        row = values[r - 1]
        for c in range(c1, min(c2, len(row)) + 1):
            if str(row[c - 1]).strip() and not any(_inside(r, c, m) for m in ignore):
                return False
    return True


def merges_on_row(merges: List[dict], sheet_id: int, row: int,
                  min_col: int) -> List[dict]:
    """Existing merges whose top-left cell is on `row` at or right of
    `min_col` (1-indexed) — last week's picture block, wherever it started."""
    return [m for m in merges
            if m.get("sheetId") == sheet_id
            and m.get("startRowIndex") == row - 1
            and m.get("startColumnIndex", -1) >= min_col - 1]
