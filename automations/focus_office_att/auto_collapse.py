"""Auto-collapse / expand the per-day column groups based on whether
that day's breakdown cells have any data. A day with no data shows
just its 'Total Apps' col (collapsed); a day with any data shows the
full 11-metric breakdown (expanded).

Same pattern for the Weekly Total breakdown group.

Run on a single tab (called from step 5) or sweep all tabs:
    .venv/bin/python -m automations.focus_office_att.auto_collapse
"""
from __future__ import annotations

import sys

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"

# Per-group: (label, group_start_col_1based, group_end_col_1based)
GROUPS = [
    ("Weekly Total breakdown", 3, 11),
    ("Mon breakdown", 13, 23),
    ("Tue breakdown", 25, 35),
    ("Wed breakdown", 37, 47),
    ("Thu breakdown", 49, 59),
    ("Fri breakdown", 61, 71),
    ("Sat breakdown", 73, 83),
    ("Sun breakdown", 85, 95),
]


def _col_letter(col: int) -> str:
    s, n = "", col
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _has_data_in_range(grid: list[list[str]], col_start_1based: int, col_end_1based: int) -> bool:
    """grid is full data (rows × cols). Returns True if any cell in the
    given column range (across all rows) has a non-empty trimmed value."""
    cs = col_start_1based - 1
    ce = col_end_1based  # half-open per slice
    for row in grid:
        for cell in row[cs:ce]:
            if cell and str(cell).strip():
                return True
    return False


def update_collapse_states(ws) -> None:
    """For each existing column group on the worksheet, set collapsed=True
    if no data exists in that group's columns, otherwise expanded.

    Reads the ACTUAL group ranges from sheet metadata (not hardcoded), so
    this works even if columns have been shifted by manual edits."""
    md = ws.spreadsheet.fetch_sheet_metadata(params={
        "fields": "sheets(properties,columnGroups)",
    })
    # Find this tab's column groups
    column_groups = []
    for s in md.get("sheets", []):
        if s["properties"].get("sheetId") == ws.id:
            column_groups = s.get("columnGroups", [])
            break
    if not column_groups:
        return  # nothing to collapse

    # Read the full data area once. Get the widest range across all groups.
    max_col = max(g.get("range", {}).get("endIndex", 0) for g in column_groups)
    last_row = max(3, ws.row_count)
    rng = f"A3:{_col_letter(max_col)}{last_row}"
    try:
        grid = ws.get(rng)
    except Exception:
        grid = []

    requests = []
    for g in column_groups:
        rng_meta = g.get("range", {})
        start_0 = rng_meta.get("startIndex", 0)        # 0-indexed
        end_0 = rng_meta.get("endIndex", 0)            # half-open
        # Convert to 1-based for the data lookup
        has_data = _has_data_in_range(grid, start_0 + 1, end_0)
        requests.append({
            "updateDimensionGroup": {
                "dimensionGroup": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": start_0,
                        "endIndex": end_0,
                    },
                    "depth": g.get("depth", 1),
                    "collapsed": not has_data,
                },
                "fields": "collapsed",
            },
        })
    ws.spreadsheet.batch_update({"requests": requests})


def main() -> int:
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    tabs = sh.worksheets()
    print(f"updating collapse states on {len(tabs)} tab(s)…")
    for ws in tabs:
        try:
            update_collapse_states(ws)
            print(f"  ✓ {ws.title}")
        except Exception as e:
            print(f"  ✗ {ws.title}: {e}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
