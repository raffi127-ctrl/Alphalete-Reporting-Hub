"""Set every cell on every tab to horizontal=CENTER + vertical=MIDDLE.

Touches only the alignment fields — backgrounds, borders, font weight,
colors, number formats, and cell values/formulas are left alone.

Scope per tab: A1..CQ200 (cols 1..95, rows 1..200).

Run:
    .venv/bin/python -m automations.focus_office_att.center_all_cells --dry-run
    .venv/bin/python -m automations.focus_office_att.center_all_cells
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
LAST_DATA_COL = 95   # matches apply_data_border.LAST_DATA_COL — CQ
LAST_ROW = 200


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
    return logging.getLogger("focus-office-att-center")


def center_all(ws) -> None:
    """Apply CENTER + MIDDLE alignment to every cell in the data range."""
    ws.spreadsheet.batch_update({"requests": [{
        "repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": 0,
                "endRowIndex": LAST_ROW,
                "startColumnIndex": 0,
                "endColumnIndex": LAST_DATA_COL,
            },
            "cell": {
                "userEnteredFormat": {
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                },
            },
            "fields": "userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment",
        },
    }]})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="List tabs without modifying alignment.")
    args = ap.parse_args()

    log = _setup_logging()
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    tabs = sh.worksheets()
    mode = "DRY-RUN" if args.dry_run else "APPLYING"
    log.info("=== %s — center+middle alignment on %d tab(s) ===", mode, len(tabs))
    for ws in tabs:
        try:
            if args.dry_run:
                log.info("  • %s (would center A1..CQ%d)", ws.title, LAST_ROW)
            else:
                center_all(ws)
                log.info("  ✓ %s", ws.title)
        except Exception as e:
            log.error("  ✗ %s: %s: %s", ws.title, type(e).__name__, str(e)[:120])
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
