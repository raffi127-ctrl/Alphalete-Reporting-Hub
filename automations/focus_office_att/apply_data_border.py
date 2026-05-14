"""Draw a bold outer border around the filled data area on the Template
(rows 1-2 headers + however many rep rows are populated). Reusable —
the scraper will call apply_bold_border(ws) after writing rep rows so
the border auto-extends to enclose the new data.

Also clears any leftover placeholder rep rows from the Template so the
propagation step starts from a clean slate.

Run:
    .venv/bin/python -m automations.focus_office_att.apply_data_border
    .venv/bin/python -m automations.focus_office_att.apply_data_border --keep-placeholders
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TEMPLATE_TAB = "Template"
LAST_DATA_COL = 95   # Sunday's "New Lines"
BLACK = {"red": 0.0, "green": 0.0, "blue": 0.0}


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
    return logging.getLogger("focus-office-att-border")


def apply_bold_border(ws, last_data_col: int = LAST_DATA_COL) -> None:
    """Draw a thick black outer border enclosing rows 1..last-rep-row × cols
    1..last_data_col. last-rep-row = last row in col B (Rep Name) that has a
    value — col B is the source of truth for "is this a real rep row?". Col A
    is the auto-formulated count and can't be used as the signal.
    Defaults to row 2 if no rep rows yet, so the headers always get bordered.

    Strategy:
      - Wipe any existing borders in the data range first (so re-runs don't
        leave stale lines from a previously-larger area).
      - Then draw thick top/bottom/left/right around the current populated area.
    """
    rep_names = ws.col_values(2)
    last_rep_row = 2  # row 2 (headers) at minimum
    for i, v in enumerate(rep_names, start=1):
        if i >= 3 and (v or "").strip():
            last_rep_row = i
    sheet_id = ws.id

    requests = [
        # Wipe any existing borders in the entire data band first
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": ws.row_count,
                    "startColumnIndex": 0,
                    "endColumnIndex": last_data_col,
                },
                "top": {"style": "NONE"}, "bottom": {"style": "NONE"},
                "left": {"style": "NONE"}, "right": {"style": "NONE"},
                "innerHorizontal": {"style": "NONE"},
                "innerVertical": {"style": "NONE"},
            },
        },
        # Then draw the bold outer border around the current populated area
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,                  # row 1
                    "endRowIndex": last_rep_row,        # exclusive: includes last_rep_row
                    "startColumnIndex": 0,               # col 1
                    "endColumnIndex": last_data_col,    # exclusive: includes col 95
                },
                "top":    {"style": "SOLID_THICK", "color": BLACK},
                "bottom": {"style": "SOLID_THICK", "color": BLACK},
                "left":   {"style": "SOLID_THICK", "color": BLACK},
                "right":  {"style": "SOLID_THICK", "color": BLACK},
            },
        },
    ]
    ws.spreadsheet.batch_update({"requests": requests})


def clear_placeholder_rows(ws) -> int:
    """Wipe all values in rows 3+ (everything below the headers). Returns
    how many cells were cleared. Conditional formatting handles the visual
    cleanup automatically — empty rows look invisible."""
    last_data_col = LAST_DATA_COL
    last_row = ws.row_count
    cell_count_before = sum(1 for cell in ws.col_values(1)[2:] if cell.strip())
    if cell_count_before == 0:
        return 0
    # Clear values from A3 to <last_data_col_letter><last_row>
    def col_letter(n: int) -> str:
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s
    rng = f"A3:{col_letter(last_data_col)}{last_row}"
    ws.batch_clear([rng])
    return cell_count_before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-placeholders", action="store_true",
                    help="Don't clear placeholder rep rows — just apply the border.")
    ap.add_argument("--all-tabs", action="store_true",
                    help="Re-apply the border on every tab (Template + all owner tabs).")
    args = ap.parse_args()

    log = _setup_logging()
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

    if args.all_tabs:
        tabs = sh.worksheets()
        log.info("redrawing bold border on %d tab(s)", len(tabs))
        for ws in tabs:
            try:
                apply_bold_border(ws)
                log.info("  ✓ %s", ws.title)
            except Exception as e:
                log.error("  ✗ %s: %s: %s", ws.title, type(e).__name__, str(e)[:120])
        return 0

    ws = sh.worksheet(TEMPLATE_TAB)
    if not args.keep_placeholders:
        cleared = clear_placeholder_rows(ws)
        log.info("cleared %d placeholder rep row(s)", cleared)

    apply_bold_border(ws)
    log.info("applied bold outer border around current populated area")
    return 0


if __name__ == "__main__":
    sys.exit(main())
