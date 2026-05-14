"""Clear Raf's pre-existing auto-formulas from the "Total Apps" columns on
every tab of the Focus Office Sheet.

Background: before automation work started, Raf seeded each Total Apps
column with a formula that resolves to 0 when there's no data — leaving a
sea of zeros across every tab. We want those columns blank in rows 3+ so
the scraper (Phase 2) can fill clean values.

What it does:
  1. Reads row 2 of the Template tab to locate every column whose header
     is "Total Apps" (case-insensitive). This includes the Weekly Total
     Apps col (B) and each daily Total Apps col (L, X, AJ, AV, BH, BT, CF
     post-structural-fix).
  2. On every tab in the Sheet (Template + every owner tab), clears the
     userEnteredValue for those columns in rows 3..200 — formula and value
     both go away, formatting stays intact.

Run:
    .venv/bin/python -m automations.focus_office_att.clear_total_apps_formulas --dry-run
    .venv/bin/python -m automations.focus_office_att.clear_total_apps_formulas
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TEMPLATE_TAB = "Template"
TARGET_HEADER = "total apps"  # case-insensitive match against row 2
DATA_ROW_START = 3            # 1-based; row 1 is title, row 2 is header
DATA_ROW_END = 200            # inclusive — covers any reasonable rep count


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
    return logging.getLogger("focus-office-att-clear-total-apps")


def _col_letter(col_idx_1based: int) -> str:
    s = ""
    n = col_idx_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def find_total_apps_columns(template_ws) -> list[int]:
    """Return 1-based column indices whose row-2 header contains 'total apps'."""
    row2 = template_ws.row_values(2)
    cols: list[int] = []
    for i, label in enumerate(row2, start=1):
        if TARGET_HEADER in (label or "").strip().lower():
            cols.append(i)
    return cols


def clear_columns_on_tab(ws, col_indices: list[int], dry_run: bool) -> int:
    """Clear userEnteredValue for the given columns in rows DATA_ROW_START..DATA_ROW_END.

    Returns the number of (col × row) cells affected (or that would be affected).
    """
    n_rows = DATA_ROW_END - DATA_ROW_START + 1
    total_cells = n_rows * len(col_indices)
    if dry_run:
        return total_cells

    sheet_id = ws.id
    requests = []
    for col in col_indices:
        requests.append({
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": DATA_ROW_START - 1,   # 0-indexed
                    "endRowIndex": DATA_ROW_END,           # exclusive
                    "startColumnIndex": col - 1,
                    "endColumnIndex": col,
                },
                # No "rows" key + fields=userEnteredValue → clears formulas/values,
                # leaves formatting (background, borders, etc.) untouched.
                "fields": "userEnteredValue",
            },
        })
    ws.spreadsheet.batch_update({"requests": requests})
    return total_cells


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be cleared without modifying the Sheet.")
    args = ap.parse_args()

    log = _setup_logging()
    log.info("opening Sheet %s", DEST_SPREADSHEET_ID)
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

    try:
        template_ws = sh.worksheet(TEMPLATE_TAB)
    except Exception:
        log.error("Template tab not found — aborting.")
        return 1

    cols = find_total_apps_columns(template_ws)
    if not cols:
        log.error("No 'Total Apps' columns found in Template row 2 — aborting.")
        return 1
    pretty = ", ".join(f"{_col_letter(c)}({c})" for c in cols)
    log.info("found %d Total Apps column(s) in Template: %s", len(cols), pretty)
    log.info("will clear rows %d..%d in those columns on every tab",
             DATA_ROW_START, DATA_ROW_END)

    tabs = sh.worksheets()
    log.info("%d tab(s) total (Template + owner tabs)", len(tabs))

    mode = "DRY-RUN" if args.dry_run else "APPLYING"
    log.info("=== %s ===", mode)
    grand_total = 0
    for ws in tabs:
        try:
            n = clear_columns_on_tab(ws, cols, dry_run=args.dry_run)
            grand_total += n
            verb = "would clear" if args.dry_run else "cleared"
            log.info("  ✓ %s — %s %d cell(s)", ws.title, verb, n)
        except Exception as e:
            log.error("  ✗ %s: %s: %s", ws.title, type(e).__name__, str(e)[:120])

    log.info("done — %s %d cell(s) across %d tab(s)",
             "would clear" if args.dry_run else "cleared",
             grand_total, len(tabs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
