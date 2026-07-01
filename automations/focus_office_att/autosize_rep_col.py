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
COUNT_COL_WIDTH_PX = 38        # col A (rep number) — narrow but readable (was 14)

# Weekly Total block = cols C..L (1-based 3..12). Autosize to header
# plus a small padding bump (smaller than day cols' 8px) so the header
# isn't crammed against the cell edge. Per Megan: 'a touch wider' than
# exact-header-fit.
WEEKLY_COL_START = 3   # col C (SUM Total Apps)
WEEKLY_COL_END = 12    # col L (SUM New Lines)
WEEKLY_COL_PADDING_PX = 6

# Col C ('SUM Total Apps') is PINNED, not auto-measured. autoResize sizes a
# col against EVERY cell in it, incl. the frozen LAST WEEK block's long
# C-banner (C111 'Weekly Total Mon X/X - Sun X/X …'). The C1 clear below only
# covers the current-week banner, so col C used to balloon to ~545px. A fixed
# width holds the 'SUM Total Apps' header + numbers cleanly. (Megan 2026-07-01)
SUM_APPS_COL_WIDTH_PX = 100


def merge_weekly_banner(ws) -> None:
    """Merge C1:L1 — the row-1 'Weekly Total Mon X/X - Sun X/X' banner —
    + center-align so it sits over the middle of the weekly block.

    Why: the merge makes the banner span the full weekly block visually,
    matching the section it labels. (Note: the merge alone doesn't stop
    autoResize from widening col C — the caller must clear/restore C1
    around the autoResize call to handle that.)

    Idempotent — unmerges first, then re-merges, since mergeCells errors
    on an already-merged range.
    """
    weekly_range = {
        "sheetId": ws.id,
        "startRowIndex": 0,
        "endRowIndex": 1,
        "startColumnIndex": WEEKLY_COL_START - 1,
        "endColumnIndex": WEEKLY_COL_END,
    }
    ws.spreadsheet.batch_update({"requests": [
        {"unmergeCells": {"range": weekly_range}},
        {"mergeCells": {"range": weekly_range, "mergeType": "MERGE_ALL"}},
        {
            "repeatCell": {
                "range": weekly_range,
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            },
        },
    ]})


# Day-block ranges for row-1 label merges. Each tuple = (start_col, end_col)
# 1-based, inclusive. Mirrors recolor_template.DAY_COLUMNS but only the
# (ta_col, group_end) pair so the label spans Total Apps + breakdown.
DAY_BANNER_RANGES = [
    (13, 24),   # Mon  M..X
    (25, 36),   # Tue  Y..AJ
    (37, 48),   # Wed  AK..AV
    (49, 60),   # Thu  AW..BH
    (61, 72),   # Fri  BI..BT
    (73, 84),   # Sat  BU..CF
    (85, 96),   # Sun  CG..CR
]


def merge_day_banners(ws) -> None:
    """Merge each day's row-1 label across that day's 12-col block (e.g.,
    'Mon 5/11' spans M1:X1) and center-align. Mirrors merge_weekly_banner.

    Trade-off: with the breakdown group COLLAPSED, only Total Apps col is
    visible. A center-aligned label sits at the visual center of the
    full 12-col merge — outside the visible portion when collapsed, so
    the label may not show. (Switch to 'LEFT' alignment if that matters
    more than the centered look in expanded view.)

    Idempotent — unmerges first then re-merges.
    """
    requests: list[dict] = []
    for start_col, end_col in DAY_BANNER_RANGES:
        day_range = {
            "sheetId": ws.id,
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": start_col - 1,
            "endColumnIndex": end_col,
        }
        requests.append({"unmergeCells": {"range": day_range}})
        requests.append({"mergeCells": {"range": day_range, "mergeType": "MERGE_ALL"}})
        requests.append({
            "repeatCell": {
                "range": day_range,
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            },
        })
    ws.spreadsheet.batch_update({"requests": requests})


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

    Weekly Total cols (C..L) get NO padding — autosize fits them exactly
    to their header text. Per Megan: 'SUM Total Apps' etc. should be
    only as wide as the header, no extra whitespace.

    Col A (count) is left alone — it's intentionally narrow.
    """
    # Step 0: temporarily clear the C1 banner formula so autoResize doesn't
    # measure col C against its 32-char string ('Weekly Total Mon X/X -
    # Sun X/X'). Restored after autoResize. The C1:L1 merge alone doesn't
    # prevent this — autoResize still reads the anchored cell's content.
    c1_formula_resp = ws.get("C1", value_render_option="FORMULA")
    c1_formula = c1_formula_resp[0][0] if c1_formula_resp and c1_formula_resp[0] else ""
    ws.spreadsheet.batch_update({"requests": [{
        "updateCells": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": WEEKLY_COL_START - 1, "endColumnIndex": WEEKLY_COL_START},
            "fields": "userEnteredValue",
            "rows": [{"values": [{"userEnteredValue": {"stringValue": ""}}]}],
        },
    }]})

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
            # Col A (rep count) — set to a fixed narrow-but-readable width
            # so it survives wipes. Don't rely on autosize since '1'/'22'
            # would size it tiny.
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                              "startIndex": 0, "endIndex": 1},
                    "properties": {"pixelSize": COUNT_COL_WIDTH_PX},
                    "fields": "pixelSize",
                },
            })
            continue
        current = widths[col_0idx]
        if col_0idx == rep_name_col - 1:
            new_width = max(current + REP_NAME_COL_PADDING_PX, REP_NAME_COL_MIN_PX)
        elif col_0idx == WEEKLY_COL_START - 1:
            # Col C is pinned — see SUM_APPS_COL_WIDTH_PX. Never trust the
            # autoResized `current` here (the frozen C-banner inflates it).
            new_width = SUM_APPS_COL_WIDTH_PX
        elif WEEKLY_COL_START - 1 <= col_0idx <= WEEKLY_COL_END - 1:
            new_width = current + WEEKLY_COL_PADDING_PX
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

    # Step 4: restore the C1 banner formula + ensure the C1:L1 merge +
    # merge each day's row-1 label across its 12-col block.
    if c1_formula:
        ws.update("C1", [[c1_formula]], value_input_option="USER_ENTERED")
    merge_weekly_banner(ws)
    merge_day_banners(ws)


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
