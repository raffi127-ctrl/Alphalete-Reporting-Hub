"""Config + data helpers for the Sales Board sections of the Captainship
drafts (Product Summary + Captainship Units). The actual images are real
browser screenshots — see sheet_shot.py; this module owns WHERE to look:

  * PS_ROWS / UNITS_ROWS — per-captain row ranges (given by Megan).
  * units_day_columns(captain_key) — which 3-col day group to show next
    to the 'Total for week' group: the most recent day WITH DATA.

Row ranges are per-captain constants; everything inside them (day groups,
WE headers) is found by label, never by hardcoded offsets.
"""
from __future__ import annotations

import contextlib

from automations.recruiting_report import fill as _rf

# Current Org Sales Board workbook (migrated off the old 1Ez-mbRO… workbook —
# that ID is still valid but is the "All in One Local Office - Raf" workbook used
# by other reports; the live Sales Board now lives here). Repointed 2026-07-03.
SALES_BOARD_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
SALES_BOARD_TAB = "Alphalete ORG Sales Board"
# ⚠ PS_ROWS / UNITS_ROWS below are OLD-LAYOUT row ranges (from the old workbook).
# They are dormant (Phase-1 drafts are churn-only) but WILL be wrong on this
# workbook's layout — re-derive them BY LABEL before wiring the Product Summary /
# Units sections in. [[feedback_no_hardcoded_columns]]

# Product Summary ranges (inclusive sheet rows).
PS_ROWS = {
    "rafael": (197, 382), "carlos": (385, 499), "eveliz": (502, 603),
    "wayne": (606, 706), "starr": (710, 777), "aron": (781, 864),
    "khalil": (868, 939), "colten": (943, 1028), "jairo": (1034, 1097),
    "luis": (1101, 1142),
}

# Captainship Units ranges (inclusive sheet rows).
UNITS_ROWS = {
    "rafael": (1197, 1230), "carlos": (1233, 1247), "eveliz": (1250, 1258),
    "wayne": (1261, 1272), "starr": (1275, 1283), "aron": (1286, 1302),
    "khalil": (1305, 1315), "colten": (1318, 1335), "jairo": (1338, 1345),
    "luis": (1389, 1397),
}

# How many columns the Product Summary block spans (A..K). The daily +
# weekly tables top out at the 'Grand Total' column at K; the vertical
# weekly-historical detail lives in COLLAPSED ROW GROUPS inside the row
# range (expanded for the screenshot by sheet_shot).
PS_END_COL = "K"

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday")


def _open_ws():
    return _rf._client().open_by_key(SALES_BOARD_ID).worksheet(SALES_BOARD_TAB)


def _to_num(s: str):
    s = (s or "").strip().replace(",", "").rstrip("%")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


@contextlib.contextmanager
def ps_groups_expanded(captain_key: str):
    """Temporarily EXPAND every collapsed row group overlapping the
    captain's Product Summary block (the vertical weekly historicals live
    in those groups), restoring the exact prior collapsed state on exit.

    Group collapse state is SHARED — anyone viewing the Sales Board sees
    the groups expanded while the screenshot runs (~30-60s). Approved by
    Megan 2026-06-04. Per the API, updating `collapsed` also sets the
    contained rows hidden/visible, so no separate visibility request is
    needed. Yields the number of groups expanded."""
    ws = _open_ws()
    start, end = PS_ROWS[captain_key]
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),rowGroups)"})
    groups = next((sh.get("rowGroups", []) for sh in meta["sheets"]
                   if sh["properties"]["sheetId"] == ws.id), [])
    to_expand = [g for g in groups
                 if g.get("collapsed", False)
                 and g["range"].get("startIndex", 0) < end
                 and g["range"].get("endIndex", 0) > start - 1]

    def _set(collapsed: bool):
        reqs = []
        for g in to_expand:
            rng = dict(g["range"])
            rng.setdefault("sheetId", ws.id)
            rng.setdefault("dimension", "ROWS")
            reqs.append({"updateDimensionGroup": {
                "dimensionGroup": {"range": rng, "depth": g["depth"],
                                   "collapsed": collapsed},
                "fields": "collapsed"}})
        if reqs:
            ws.spreadsheet.batch_update({"requests": reqs})

    _set(False)
    try:
        yield len(to_expand)
    finally:
        _set(True)   # restore — only groups that WERE collapsed


def units_day_columns(captain_key: str):
    """(day_name, first_col_letter, last_col_letter) of the most recent
    day group WITH DATA in the captain's Captainship Units block: the
    day-name headers (first row of the block) mark each 3-col group;
    keep the rightmost whose total-row 'This week' cell is non-zero."""
    from gspread.utils import rowcol_to_a1
    start, end = UNITS_ROWS[captain_key]
    grid = _open_ws().get(f"B{start}:W{end}")
    if not grid:
        raise ValueError(f"empty units range for {captain_key}")
    day_cols = {}
    for i, v in enumerate(grid[0]):
        if (v or "").strip() in _DAYS:
            day_cols[(v or "").strip()] = i
    total_row = grid[2:][-1] if len(grid) > 2 else []
    chosen = None
    for day in _DAYS:
        c = day_cols.get(day)
        if c is None:
            continue
        v = _to_num(total_row[c]) if c < len(total_row) else None
        if v:
            chosen = (day, c)
    if chosen is None:   # nothing filled yet (e.g. Monday AM) -> rightmost
        day = max(day_cols, key=lambda d: day_cols[d]) if day_cols else "Monday"
        chosen = (day, day_cols.get(day, 1))
    day_name, local = chosen
    first = local + 2            # local 0 == column B == column number 2
    return (day_name,
            rowcol_to_a1(1, first)[:-1], rowcol_to_a1(1, first + 2)[:-1])
