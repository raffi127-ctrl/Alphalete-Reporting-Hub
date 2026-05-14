"""Propagate the finalized Template to all 30 owner tabs.

Strategy:
  1. Delete every existing tab whose name is in OWNERS (from setup_tabs).
  2. Duplicate Template once per owner (alphabetized).
  3. Reorder so Template is first, owners are alphabetical.

Each new owner tab inherits everything from Template:
  - 11-metric structure on every weekday
  - Self-updating date formulas (Mon 5/11, Tue 5/12, ...)
  - Conditional formatting (colors only show on rows with a rep name)
  - Frozen rows 1-2 + col 1
  - Number formats per col type
  - Headers (deep navy / pale blue)
  - Bold outer border around populated area
  - Raf's column groups (Mon expanded, Tue-Sun collapsed)

Run:
    .venv/bin/python -m automations.focus_office_att.propagate_template --dry-run
    .venv/bin/python -m automations.focus_office_att.propagate_template
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.setup_tabs import OWNERS, TEMPLATE_TAB, DEST_SPREADSHEET_ID


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
    return logging.getLogger("focus-office-att-propagate")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print planned operations without modifying the Sheet.")
    args = ap.parse_args()

    log = _setup_logging()
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

    existing = {ws.title: ws for ws in sh.worksheets()}
    log.info("Sheet has %d tabs total", len(existing))

    if TEMPLATE_TAB not in existing:
        log.error("Template tab missing — aborting.")
        return 1
    template_ws = existing[TEMPLATE_TAB]

    # Step 1: delete every existing owner tab.
    to_delete = [name for name in OWNERS if name in existing]
    log.info("found %d existing owner tab(s) to delete", len(to_delete))
    for name in to_delete:
        if args.dry_run:
            log.info("  [DRY-RUN] would delete '%s'", name)
        else:
            sh.del_worksheet(existing[name])
            log.info("  deleted '%s'", name)

    # Step 2: duplicate Template once per owner (alphabetized).
    log.info("creating %d new owner tabs from Template", len(OWNERS))
    new_tabs: list = []
    for name in OWNERS:
        if args.dry_run:
            log.info("  [DRY-RUN] would duplicate Template → '%s'", name)
            continue
        try:
            new_ws = sh.duplicate_sheet(
                source_sheet_id=template_ws.id,
                new_sheet_name=name,
            )
            log.info("  [OK] '%s' (id=%s)", name, new_ws.id)
            new_tabs.append(new_ws)
        except Exception as e:
            log.exception("  [FAIL] couldn't create '%s': %s", name, e)

    # Step 3: reorder — Template first, owners alphabetical.
    if not args.dry_run:
        all_ws = sh.worksheets()
        non_template = sorted(
            (w for w in all_ws if w.title != TEMPLATE_TAB),
            key=lambda w: w.title.lower(),
        )
        desired = [next(w for w in all_ws if w.title == TEMPLATE_TAB)] + non_template
        requests = [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": w.id, "index": idx},
                    "fields": "index",
                },
            }
            for idx, w in enumerate(desired)
        ]
        sh.batch_update({"requests": requests})
        log.info("reordered tabs — Template first, owners alphabetical")
    else:
        log.info("[DRY-RUN] would reorder: Template first, then alphabetical")

    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
