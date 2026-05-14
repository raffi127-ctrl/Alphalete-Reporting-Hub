"""Auto-resize columns to fit content on every tab (Template + all 30
owner tabs). Idempotent — re-run any time content gets added that doesn't
fit.

Two helpers:
  - autosize_col_a(ws): just the Rep Name column.
  - autosize_all_data_cols(ws): every data column (A..CQ, 1..95). Use this
    after rep data has been filled in by the scraper.

Run:
    .venv/bin/python -m automations.focus_office_att.autosize_rep_col
    .venv/bin/python -m automations.focus_office_att.autosize_rep_col --all-cols
"""
from __future__ import annotations

import argparse
import sys

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
LAST_DATA_COL = 95   # Sunday's "New Lines" (matches apply_data_border.LAST_DATA_COL)


def autosize_col_a(ws) -> None:
    """Auto-fit col A on a single worksheet to the widest rep name."""
    ws.spreadsheet.batch_update({"requests": [{
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId": ws.id,
                "dimension": "COLUMNS",
                "startIndex": 0,   # col A
                "endIndex": 1,
            },
        },
    }]})


REP_NAME_COL_PADDING_PX = 12   # added after autosize so bold names don't clip
REP_NAME_COL_MIN_PX = 160      # roomy default even when no names are filled yet
PER_COL_PADDING_PX = 8         # minimal breathing room (was 30 — too wide per Megan)


def autosize_all_data_cols(ws, last_data_col: int = LAST_DATA_COL,
                            rep_name_col: int = 2) -> None:
    """Auto-fit every data column (A..last_data_col), then add per-column
    padding so adjacent headers don't visually run into each other.

    Why padding? Google's autoResize sizes a col to the EXACT pixel width
    of its longest content. With wrapStrategy=OVERFLOW_CELL (no wrap),
    that means adjacent col headers butt up against each other with no
    whitespace, e.g. "Total Leads KnockedTalk To's". A small per-col
    pixel bump (PER_COL_PADDING_PX) gives every cell breathing room.

    Rep Name col gets an extra bump (REP_NAME_COL_PADDING_PX) plus a
    REP_NAME_COL_MIN_PX floor — bold rep names need more buffer than
    plain numeric cols, and the col should never be tiny.

    Col A (count) is left alone — it's intentionally narrow.
    """
    # Step 1: auto-resize every data col.
    ws.spreadsheet.batch_update({"requests": [{
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId": ws.id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": last_data_col,
            },
        },
    }]})

    # Step 2: read current widths so we can compute per-col bumps.
    md = ws.spreadsheet.fetch_sheet_metadata(params={
        "fields": "sheets(properties(sheetId),data(columnMetadata(pixelSize)))",
    })
    widths: list = []
    for sd in md.get("sheets", []):
        if sd.get("properties", {}).get("sheetId") != ws.id:
            continue
        widths = [c.get("pixelSize") for c in sd.get("data", [{}])[0].get("columnMetadata", [])]
        break

    # Step 3: build per-col bump requests.
    requests = []
    for col_0idx in range(last_data_col):
        if col_0idx >= len(widths) or widths[col_0idx] is None:
            continue
        if col_0idx == 0:
            continue  # col A (count) left as-is
        current = widths[col_0idx]
        if col_0idx == rep_name_col - 1:
            new_width = max(current + REP_NAME_COL_PADDING_PX, REP_NAME_COL_MIN_PX)
        else:
            new_width = current + PER_COL_PADDING_PX
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": col_0idx,
                    "endIndex": col_0idx + 1,
                },
                "properties": {"pixelSize": new_width},
                "fields": "pixelSize",
            },
        })
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-cols", action="store_true",
                    help="Auto-resize every data column (A..CQ), not just col A. "
                         "Use AFTER scraper has filled real values.")
    args = ap.parse_args()

    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    tabs = sh.worksheets()
    target = "all data cols (A..CQ)" if args.all_cols else "col A"
    print(f"auto-resizing {target} on {len(tabs)} tab(s)…")
    for ws in tabs:
        try:
            if args.all_cols:
                autosize_all_data_cols(ws)
            else:
                autosize_col_a(ws)
            print(f"  ✓ {ws.title}")
        except Exception as e:
            print(f"  ✗ {ws.title}: {e}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
