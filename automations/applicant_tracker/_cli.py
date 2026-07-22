"""Shared command-line entrypoint for the four applicant_tracker reports.

Every report exposes `run(target=None)`; this wraps it with the flags the Hub
buttons and manual testing need:

  --dry-run        exercise the whole report (login + scrape) but write NOTHING
                   to the Sheet -- prints what it *would* write instead. This is
                   how you preview safely (Eve rule: --dry-run while testing).
  --office ID      limit to one or more office ids (repeatable). Use it to
                   preview a single office before a full 17-office run.
  --date Y-M-D     override the target date (defaults per report: yesterday or
                   today). Handy for backfilling or re-checking a specific day.
"""
from __future__ import annotations

import argparse
import datetime as dt

from . import config
from . import sheets


def main(run_fn) -> None:
    p = argparse.ArgumentParser(description=run_fn.__module__)
    p.add_argument("--dry-run", action="store_true",
                   help="run end to end but send NO writes to the Sheet")
    p.add_argument("--office", action="append", metavar="ID",
                   help="limit to office id(s); repeatable (default: all offices)")
    p.add_argument("--date", metavar="YYYY-MM-DD",
                   help="override the target date (default: per-report)")
    a = p.parse_args()

    if a.dry_run:
        sheets.DRY_RUN = True
        print("[dry-run] exercising the report — NO writes will reach the Sheet")
    if a.office:
        keep = {str(o).strip() for o in a.office}
        config.OFFICE_IDS = [o for o in config.OFFICE_IDS if o in keep]
        config.OFFICE_IDS_FIRST_DAY = [o for o in config.OFFICE_IDS_FIRST_DAY if o in keep]
        print(f"[office filter] limited to: {sorted(keep)}")
    target = dt.date.fromisoformat(a.date) if a.date else None

    run_fn(target)
