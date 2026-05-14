"""Phase 1 scaffolder for the Focus Office: Sales Org -ATT Program report.

Reads the OWNERS list below; for each owner, ensures a tab exists in the
destination Sheet by duplicating the 'Template' tab and renaming it to
the owner's name. Idempotent — owners that already have a tab are skipped.

Also (one-time): deletes the empty 'Owners Names' tab if present.

Run:
    .venv/bin/python -m automations.focus_office_att.setup_tabs
    .venv/bin/python -m automations.focus_office_att.setup_tabs --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import gspread

# Reuse the existing OAuth client + retry helpers from the recruiting_report
# module so this report shares one Google sign-in across all automations.
from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TEMPLATE_TAB = "Template"
OWNERS_NAMES_TAB = "Owners Names"

# The 30 owners we're scaffolding tabs for. Source-of-truth going forward
# is the actual list of tabs in the Sheet — this list is just for the
# initial bulk-create. Add new owners by re-running with their name added.
# Stored sorted so the create order matches the final on-Sheet order.
OWNERS = sorted([
    "Rafael Hidalgo",
    "John Richard Young",
    "Jose Antonio Chavez",
    "Trang Canavan",
    "Nicholas Weldon",
    "Eric Martinez",
    "Nii Tagoe",
    "Cody Cannon",
    "Tevin Sterling",
    "Natalia Gwarda",
    "Kash Rai",
    "Lamar Mitchell",
    "Haytham Nagi",
    "Aya Al-Khafaji",
    "Marcellus Butler",
    "Marcial Rodriguez",
    "Salik Mallick",
    "Cyrus Wade",
    "Muhammad Haque",
    "Edgar Muniz II",
    "Jacob Morgan",
    "Steve McElwee",
    "German Lopez",
    "Joseph Logan",
    "Sam Park",
    "Kiarri McBroom",
    "Melik El Jaiez",
    "Jennifer Figueroa",
    "Carissa Ng",
    "Kim Rodriguez",
])


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
    return logging.getLogger("focus-office-att")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="List planned actions without modifying the Sheet.")
    args = ap.parse_args()

    log = _setup_logging()
    log.info("opening Sheet %s", DEST_SPREADSHEET_ID)
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

    existing = {ws.title: ws for ws in sh.worksheets()}
    log.info("Sheet has %d existing tabs", len(existing))

    # Sanity: Template must exist — we can't create owner tabs without it.
    if TEMPLATE_TAB not in existing:
        log.error("'%s' tab is missing — can't duplicate. Aborting.", TEMPLATE_TAB)
        return 1
    template_ws = existing[TEMPLATE_TAB]

    # One-time: drop the empty 'Owners Names' tab.
    if OWNERS_NAMES_TAB in existing:
        if args.dry_run:
            log.info("[DRY-RUN] would delete tab '%s'", OWNERS_NAMES_TAB)
        else:
            sh.del_worksheet(existing[OWNERS_NAMES_TAB])
            log.info("deleted tab '%s'", OWNERS_NAMES_TAB)
            existing.pop(OWNERS_NAMES_TAB, None)

    created, skipped = 0, 0
    for owner in OWNERS:
        if owner in existing:
            log.info("[SKIP] '%s' already has a tab", owner)
            skipped += 1
            continue
        if args.dry_run:
            log.info("[DRY-RUN] would duplicate '%s' → '%s'", TEMPLATE_TAB, owner)
            created += 1
            continue
        # gspread's duplicate_sheet handles the copy + rename atomically.
        try:
            new_ws = sh.duplicate_sheet(
                source_sheet_id=template_ws.id,
                new_sheet_name=owner,
            )
            log.info("[OK] created tab '%s' (id=%s)", owner, new_ws.id)
            created += 1
        except Exception as e:
            log.exception("[FAIL] couldn't create '%s': %s", owner, e)

    # Reorder: Template at index 0, then every other tab alphabetical.
    # Done via a single batch update so the Sheet only re-renders once.
    if not args.dry_run:
        all_ws = sh.worksheets()
        non_template = sorted(
            (w for w in all_ws if w.title != TEMPLATE_TAB),
            key=lambda w: w.title.lower(),
        )
        desired_order = [next(w for w in all_ws if w.title == TEMPLATE_TAB)] + non_template
        requests = [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": w.id, "index": idx},
                    "fields": "index",
                },
            }
            for idx, w in enumerate(desired_order)
        ]
        sh.batch_update({"requests": requests})
        log.info("reordered tabs — Template first, others alphabetical")
    else:
        log.info("[DRY-RUN] would reorder: Template first, then alphabetical")

    log.info("done — created %d, skipped %d", created, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
