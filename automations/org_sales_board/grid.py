"""Read a whole board tab — no hardcoded last row.

WHY THIS EXISTS. Three modules that walk the Org Sales Board read it with a
literal `A1:ZZ2200`: `roster_remove`, `zero_streak` and `perrep_kl_repair`. The
board is a stack of blocks that GROWS every time a captainship is added, and on
2026-09-02 Pat's and Jess's blocks pushed the last delta box to row 2273 —
past the cap. Nothing failed: the three modules simply stopped seeing the
bottom of the tab. `roster_remove` planned 12 rows for a rep who had 18, so a
removal would have left his name sitting in two delta boxes for good, and
`zero_streak` could not propose anyone out of the two newest captainships at
all.

The daily fill, `sort` and `rollover` never had the bug — they all use
`get_all_values()`. This is that, with the render option the callers need.

[[feedback_no_hardcoded_columns]] is the same rule one axis over: find the end
of the sheet by asking the sheet, never by typing a number that was true once.
"""
from __future__ import annotations


def read_grid(ws, unformatted: bool = True) -> list:
    """The tab's full rectangle, A1 to its last row/column.

    `ws.row_count` / `ws.col_count` are the tab's real extent, so this cannot
    fall short the way a literal range does. Trailing empty rows cost nothing:
    Sheets trims them out of the response, and every finder in these modules
    ends a table on a blank row anyway.

    A worksheet that does not expose those two (the test doubles) falls back to
    a range-less `get()`, which is the whole tab as well — the point is only
    that no number typed here can go stale.
    """
    opts = {"value_render_option": "UNFORMATTED_VALUE"} if unformatted else {}
    rows = getattr(ws, "row_count", None)
    cols = getattr(ws, "col_count", None)
    if isinstance(rows, int) and isinstance(cols, int):
        return ws.get(f"A1:{_a1col(cols)}{rows}", **opts) or []
    return ws.get(**opts) or []


def _a1col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s or "A"
