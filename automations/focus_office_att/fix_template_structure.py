"""One-time structural fix: make Tue-Sun column blocks match Monday's
11-metric layout in the Focus Office Template tab.

Monday already has the right structure (cols 13-23, 11 metrics):
  Total Leads Knocked, Talk To's, Presentations, First Knock,
  Last Knock Date, # of gaps, total gap time, New INT, Upgrades,
  DTV, New Lines

Tue-Sun currently have 10 metrics in their groups, with a vestigial
"Laps" column and slightly different labels:
  Laps, doors knocked, 1st Knock, Last Knock, # of gaps,
  total gap time, New INT, Upgrades, DTV, New Lines

Per-day fix:
  - Delete "Laps" column
  - Rename "doors knocked" → "Total Leads Knocked"
  - Insert 2 new columns (for Talk To's + Presentations) after TLK
  - Rename "1st Knock" → "First Knock"
  - Rename "Last Knock" → "Last Knock Date"

Net change per day: +1 column. Total: +6 columns across the sheet.

Days processed right-to-left so column-index shifts don't ripple into
days we haven't touched yet.

Run:
    .venv/bin/python -m automations.focus_office_att.fix_template_structure --dry-run
    .venv/bin/python -m automations.focus_office_att.fix_template_structure
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TEMPLATE_TAB = "Template"

# Original column positions (1-indexed) for each Tue-Sun day BEFORE any fix.
# Each tuple: (day_name, total_apps_col, group_start, group_end).
# Right-to-left order so earlier-day indices stay valid as we modify later days.
DAYS_RIGHT_TO_LEFT = [
    ("Sunday",    79, 80, 89),
    ("Saturday",  68, 69, 78),
    ("Friday",    57, 58, 67),
    ("Thursday",  46, 47, 56),
    ("Wednesday", 35, 36, 45),
    ("Tuesday",   24, 25, 34),
]

TALK_TO_LABEL = "Talk To's (Not interested + Presentations + Comeback + Sale)"
PRESENTATIONS_LABEL = "Presenations (Not interested + Sale)"


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
    return logging.getLogger("focus-office-att-fix")


def _a1(col_idx_1based: int, row: int) -> str:
    """Convert 1-based (col, row) to A1 notation."""
    s = ""
    n = col_idx_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print planned operations without modifying the Sheet.")
    args = ap.parse_args()

    log = _setup_logging()
    log.info("opening Sheet %s", DEST_SPREADSHEET_ID)
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

    try:
        ws = sh.worksheet(TEMPLATE_TAB)
    except Exception:
        log.error("Template tab not found — aborting.")
        return 1
    sheet_id = ws.id

    # Sanity-check: confirm Tue still has "Laps" at the expected col before
    # we touch anything. If the structure has already been fixed, bail.
    row2 = ws.row_values(2)
    tue_first_in_group = row2[24] if len(row2) > 24 else ""  # col 25 (0-indexed 24)
    if tue_first_in_group.strip().lower() != "laps":
        log.warning(
            "Tuesday's group col 25 is %r, not 'Laps'. Structure may already "
            "be fixed (or different from expected). Aborting to be safe.",
            tue_first_in_group,
        )
        return 1
    log.info("verified Tuesday col 25 = 'Laps' — structure matches expected pre-fix layout")

    for day_name, ta_col, gs, ge in DAYS_RIGHT_TO_LEFT:
        log.info("=== %s (Total Apps col %d, group cols %d-%d) ===",
                 day_name, ta_col, gs, ge)

        # Build the batch of structural requests for THIS day.
        # Within a single batch_update, requests execute in order — each
        # subsequent request sees post-previous-request state.
        # 0-indexed half-open ranges for the API.
        requests = [
            # 1. Delete "Laps" (col gs)
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": gs - 1,
                        "endIndex": gs,
                    },
                },
            },
            # 2. Insert 2 new cols at position (gs + 1 - 1) = gs (after the
            #    now-Total-Leads-Knocked col which is at gs after the delete)
            #    Wait — after delete, col gs is what was col gs+1 (doors knocked).
            #    We want the 2 new cols AFTER doors knocked (which we'll rename
            #    to TLK), so at position gs+1 (1-indexed) = gs (0-indexed).
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": gs,        # 0-indexed: position gs+1 (1-indexed)
                        "endIndex": gs + 2,      # insert 2 cols
                    },
                    "inheritFromBefore": True,   # inherit width/formatting from TLK col
                },
            },
        ]

        # Cell value updates (row 2 labels) — do AFTER structural changes.
        # After delete + insert, the layout is:
        #   col gs   = "doors knocked" (was at gs+1, shifted by -1, then unshifted by +2 inserts at gs... hmm)
        # Let me re-trace:
        #   BEFORE: col gs = Laps, gs+1 = doors knocked, gs+2 = 1st Knock, gs+3 = Last Knock, ...
        #   AFTER DELETE (cols shifted left by 1 from gs+1 onwards):
        #     col gs = doors knocked, gs+1 = 1st Knock, gs+2 = Last Knock, ...
        #   AFTER INSERT 2 at startIndex=gs (i.e. cols gs and gs+1 are new blank):
        #     col gs = (new), gs+1 = (new), gs+2 = doors knocked, gs+3 = 1st Knock, gs+4 = Last Knock, ...
        # That's WRONG — TLK should be at col gs (first), not the new cols.
        # FIX: insertDimension at startIndex = gs+1 (so the new cols go AFTER doors knocked):
        #     col gs = doors knocked, gs+1 = (new), gs+2 = (new), gs+3 = 1st Knock, gs+4 = Last Knock, ...
        # Rename:
        #     col gs → "Total Leads Knocked"
        #     col gs+1 → Talk To's
        #     col gs+2 → Presentations
        #     col gs+3 → First Knock (was 1st Knock)
        #     col gs+4 → Last Knock Date (was Last Knock)
        # Final group cols: gs..gs+10 (11 cols). ✓

        # Adjust the insertDimension range (the previous requests[1] has bug):
        requests[1]["insertDimension"]["range"]["startIndex"] = gs   # 0-indexed: position gs+1 (1-indexed)
        requests[1]["insertDimension"]["range"]["endIndex"] = gs + 2

        # value updates per cell, using 1-based column indices AFTER the
        # delete + insert (group is now cols gs..gs+10):
        cell_updates = [
            (gs,     "Total Leads Knocked"),     # was "doors knocked"
            (gs + 1, TALK_TO_LABEL),             # newly inserted
            (gs + 2, PRESENTATIONS_LABEL),       # newly inserted
            (gs + 3, "First Knock"),             # was "1st Knock"
            (gs + 4, "Last Knock Date"),         # was "Last Knock"
        ]

        if args.dry_run:
            log.info("  [DRY-RUN] would delete col %d (Laps)", gs)
            log.info("  [DRY-RUN] would insert 2 cols at position %d (after TLK)", gs + 1)
            for col, label in cell_updates:
                log.info("  [DRY-RUN] would set row 2 col %d → %r", col, label[:40])
            continue

        # Execute structural changes for this day.
        sh.batch_update({"requests": requests})

        # Then write the cell labels (separate request — values_batch_update is
        # fine post-structure-change).
        data = [
            {"range": f"'{TEMPLATE_TAB}'!{_a1(col, 2)}", "values": [[val]]}
            for col, val in cell_updates
        ]
        ws.spreadsheet.values_batch_update({
            "valueInputOption": "RAW",
            "data": data,
        })
        log.info("  applied: deleted Laps, inserted 2 cols, set 5 labels")

    log.info("done — Tue-Sun blocks now match Monday's 11-metric structure")
    log.info("verify the column groups still cover the right ranges (Sheets API auto-adjusts insertions/deletions inside a group's range)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
