"""Clear any background, border, or text formatting from cells past
the last data column (Sunday's "New Lines" col, col 95). Sunday's
breakdown ends at col 95 (CQ); anything in col 96+ (CR onwards) is
leftover from earlier formatting passes and should be visually clean.

Run:
    .venv/bin/python -m automations.focus_office_att.clean_overflow
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TEMPLATE_TAB = "Template"
LAST_DATA_COL = 95   # 1-indexed: Sunday's "New Lines" = col CQ


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
    return logging.getLogger("focus-office-att-clean")


def main() -> int:
    log = _setup_logging()
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    ws = sh.worksheet(TEMPLATE_TAB)
    sheet_id = ws.id
    sheet_col_count = ws.col_count

    requests = [
        # Wipe all userEnteredFormat (background, fonts, number format, borders)
        # from col LAST_DATA_COL+1 through the end of the sheet, all rows.
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startColumnIndex": LAST_DATA_COL,    # 0-indexed: col 96
                    "endColumnIndex": sheet_col_count,
                },
                "cell": {"userEnteredFormat": {}},
                "fields": "userEnteredFormat",
            },
        },
        # Explicitly clear borders too (they're a separate API surface).
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": ws.row_count,
                    "startColumnIndex": LAST_DATA_COL,
                    "endColumnIndex": sheet_col_count,
                },
                "innerHorizontal": {"style": "NONE"},
                "innerVertical": {"style": "NONE"},
                "top": {"style": "NONE"},
                "bottom": {"style": "NONE"},
                "left": {"style": "NONE"},
                "right": {"style": "NONE"},
            },
        },
    ]

    sh.batch_update({"requests": requests})
    log.info("cleared formatting on cols %d-%d (everything past Sunday's data)",
             LAST_DATA_COL + 1, sheet_col_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
