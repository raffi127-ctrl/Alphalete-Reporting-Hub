"""Apply dates + formatting to the Focus Office Template tab.

Dates: writes self-updating Sheet formulas to row 1 day cells so they
always show the current week (e.g. "Mon 5/11"). Sheet recalculates
TODAY() each open, so no script needs to "remember" to refresh.

Formatting:
  - Freeze rows 1-2 so headers stay visible while scrolling
  - Bold + colored headers (row 1 = darker tint, row 2 = lighter tint)
  - Alternating day-block banding (cool/warm shading per weekday)
  - Number formats: integers on count cols, times on knock cols
  - Auto-resize columns to fit content

Run:
    .venv/bin/python -m automations.focus_office_att.style_template --dry-run
    .venv/bin/python -m automations.focus_office_att.style_template
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TEMPLATE_TAB = "Template"

# 1-based column indices (post-structural-fix). Each weekday block is
# 12 cols wide: 1 always-visible "Total Apps" + 11 in collapsible group.
DAY_COLUMNS = [
    # (day_short, total_apps_col, group_start, group_end, day_offset_from_monday)
    ("Mon", 12, 13, 23, 0),
    ("Tue", 24, 25, 35, 1),
    ("Wed", 36, 37, 47, 2),
    ("Thu", 48, 49, 59, 3),
    ("Fri", 60, 61, 71, 4),
    ("Sat", 72, 73, 83, 5),
    ("Sun", 84, 85, 95, 6),
]
WEEKLY_TOTAL_COL = 2  # cell where "Weekly Total Mon 5/11 - Sun 5/17" goes
WEEKLY_TOTAL_GROUP_START = 3
WEEKLY_TOTAL_GROUP_END = 11

# Visual palette — cool/warm alternating to make weekday blocks easy to scan.
BAND_COLORS = [
    {"red": 0.93, "green": 0.96, "blue": 1.00},  # cool blue
    {"red": 1.00, "green": 0.97, "blue": 0.93},  # warm peach
]
HEADER_ROW1_BG = {"red": 0.20, "green": 0.34, "blue": 0.55}  # deep blue
HEADER_ROW1_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}
HEADER_ROW2_BG = {"red": 0.85, "green": 0.89, "blue": 0.95}  # pale blue
HEADER_ROW2_FG = {"red": 0.10, "green": 0.15, "blue": 0.25}


def _setup_logging() -> logging.Logger:
    import datetime as dt
    log_dir = Path(__file__).resolve().parent.parent.parent / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"focus-office-att-{dt.date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
        force=True,
    )
    return logging.getLogger("focus-office-att-style")


def _a1(col_idx_1based: int, row: int) -> str:
    s = ""
    n = col_idx_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row}"


def _day_formula(day_short: str, day_offset: int) -> str:
    """Sheet formula like ="Mon "&TEXT(TODAY()-WEEKDAY(TODAY(),2)+1,"M/d")"""
    n = day_offset + 1  # +1 because Mon = today - WEEKDAY()+1
    return f'="{day_short} "&TEXT(TODAY()-WEEKDAY(TODAY(),2)+{n},"M/d")'


def _weekly_total_formula() -> str:
    """="Weekly Total Mon 5/11 - Sun 5/17" — auto-updating range."""
    return (
        '="Weekly Total "&'
        '"Mon "&TEXT(TODAY()-WEEKDAY(TODAY(),2)+1,"M/d")&'
        '" - Sun "&TEXT(TODAY()-WEEKDAY(TODAY(),2)+7,"M/d")'
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    log = _setup_logging()

    log.info("opening Sheet")
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    ws = sh.worksheet(TEMPLATE_TAB)
    sheet_id = ws.id

    # ---- Phase A: write the date formulas ----
    formula_writes = [
        (WEEKLY_TOTAL_COL, _weekly_total_formula()),
    ]
    for short, ta_col, _gs, _ge, offset in DAY_COLUMNS:
        formula_writes.append((ta_col, _day_formula(short, offset)))

    if args.dry_run:
        log.info("[DRY-RUN] would write %d date formulas to row 1:", len(formula_writes))
        for col, f in formula_writes:
            log.info("  col %d: %s", col, f[:90] + ("…" if len(f) > 90 else ""))
    else:
        data = [
            {"range": f"'{TEMPLATE_TAB}'!{_a1(col, 1)}", "values": [[f]]}
            for col, f in formula_writes
        ]
        ws.spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",  # parse formulas
            "data": data,
        })
        log.info("wrote %d date formulas to row 1", len(formula_writes))

    # ---- Phase B: formatting via batch_update ----
    requests = []

    # B1: Freeze rows 1-2
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 2},
            },
            "fields": "gridProperties.frozenRowCount",
        },
    })

    # B2: Header row 1 — bold + dark-blue background + white text + centered
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_ROW1_BG,
                "textFormat": {"bold": True, "foregroundColor": HEADER_ROW1_FG, "fontSize": 11},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        },
    })

    # B3: Header row 2 — bold + pale-blue background + dark text + centered + small font
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2},
            "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_ROW2_BG,
                "textFormat": {"bold": True, "foregroundColor": HEADER_ROW2_FG, "fontSize": 9},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
        },
    })

    # B4: Day-block banding — paint each weekday block (rows 3+) with alternating tints.
    # Weekly Total block + 7 weekdays = 8 blocks → BAND_COLORS[i % 2].
    blocks = [(WEEKLY_TOTAL_COL, WEEKLY_TOTAL_GROUP_END)]
    for _short, ta_col, _gs, ge, _o in DAY_COLUMNS:
        blocks.append((ta_col, ge))
    for i, (start_col, end_col) in enumerate(blocks):
        bg = BAND_COLORS[i % 2]
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 2,            # row 3 onwards (data rows)
                    "endRowIndex": 200,            # cover plenty of rep rows
                    "startColumnIndex": start_col - 1,
                    "endColumnIndex": end_col,     # half-open
                },
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            },
        })

    # B5: Number formats — integer on count cols, time on knock cols.
    # Apply per-column based on row 2 label patterns.
    r2 = ws.row_values(2)
    integer_keywords = ("total apps", "doors knocked", "# of gaps", "total leads knocked",
                        "talk to", "presenation", "presentations", "new int", "upgrades",
                        "dtv", "new lines")
    time_keywords = ("first knock", "1st knock", "last knock")
    for col_idx_0based, label in enumerate(r2):
        label_low = label.strip().lower()
        if not label_low:
            continue
        fmt = None
        if any(k in label_low for k in time_keywords):
            fmt = {"type": "DATE_TIME", "pattern": "h:mm am/pm"}
        elif any(k in label_low for k in integer_keywords):
            fmt = {"type": "NUMBER", "pattern": "0"}
        if not fmt:
            continue
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 2, "endRowIndex": 200,
                    "startColumnIndex": col_idx_0based,
                    "endColumnIndex": col_idx_0based + 1,
                },
                "cell": {"userEnteredFormat": {"numberFormat": fmt}},
                "fields": "userEnteredFormat.numberFormat",
            },
        })

    # B6: Auto-resize all populated columns to fit content.
    populated_col_count = max(len(ws.row_values(1)), len(ws.row_values(2)))
    requests.append({
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": populated_col_count,
            },
        },
    })

    if args.dry_run:
        log.info("[DRY-RUN] would issue %d formatting requests "
                 "(freeze + 2 header rows + %d band blocks + %d number formats + auto-resize)",
                 len(requests), len(blocks),
                 sum(1 for r in requests if "numberFormat" in r.get("repeatCell", {}).get("fields", "")))
    else:
        sh.batch_update({"requests": requests})
        log.info("applied %d formatting requests", len(requests))

    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
