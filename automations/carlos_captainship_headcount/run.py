"""Carlos Captainship Headcount — weekly Monday hub run.

Fills a fresh week column on the "Captainship Head count" tab of the
*All In One - CARLOS* sheet with each active owner's **Rep Count**, pulled
live from Tableau (ATTTRACKER-B2B / D2D1-PAGERV3, current week). Recomputes
the Total (SUM formula) and sorts the active owners high->low.

Idempotent: if this week's column already exists it refreshes in place
instead of inserting a duplicate (override with --force-insert).

  python -m automations.carlos_captainship_headcount.run
  python -m automations.carlos_captainship_headcount.run --dry-run
  python -m automations.carlos_captainship_headcount.run --week 2026-07-05
  python -m automations.carlos_captainship_headcount.run --force-insert
  python -m automations.carlos_captainship_headcount.run --skip-download
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback

from automations.recruiting_report.opt_phase_carlos import _current_we_sunday
from automations.carlos_captainship_headcount import sheet_fill, tableau_pull

REPORT_ID = "carlos_captainship_headcount"


def _run(args) -> dict:
    we = (dt.date.fromisoformat(args.week) if args.week
          else _current_we_sunday())
    label = sheet_fill.week_label(we)
    print(f"Carlos Captainship Headcount → week ending {we} (col '{label}') "
          f"· {'DRY-RUN' if args.dry_run else 'LIVE'}", flush=True)

    # 1) Rep Counts from Tableau (live pull unless --skip-download reuses cache).
    if args.skip_download:
        counts = tableau_pull.parse_counts(tableau_pull.CACHE)
        print(f"  Tableau (cached): {len(counts)} B2B ICD rep counts", flush=True)
    else:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=True) as page:
            counts = tableau_pull.pull_rep_counts(page=page, verbose=True)
        print(f"  Tableau: {len(counts)} B2B ICD rep counts pulled", flush=True)
    if not counts:
        raise RuntimeError("Tableau returned no rep counts — aborting "
                           "(nothing filled).")

    # 2) Fill the sheet.
    ws, sh = sheet_fill.open_tab()
    rep = sheet_fill.run_fill(ws, sh, counts, we,
                              dry_run=args.dry_run,
                              force_insert=args.force_insert)

    print("\n=== " + ("PLAN" if args.dry_run else "RESULT") + " ===", flush=True)
    for line in rep["log"]:
        print(line if line.startswith("  ") else "  " + line, flush=True)
    print(f"\n  Total {rep['label']} = {rep['total']}  "
          f"({len(rep['matched'])} owners matched)", flush=True)
    if rep["ambiguous"]:
        print("  ⚠ AMBIGUOUS (pin one in sheet_fill.ALIASES): "
              + "; ".join(rep["ambiguous"]), flush=True)
    if rep["unmatched"]:
        print("  ⚠ NOT FOUND in Tableau — possible roster change; if an owner "
              "left Carlos' team move+hide their row, if new add a row: "
              + ", ".join(rep["unmatched"]), flush=True)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Carlos Captainship Headcount")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + match + show the plan, write nothing")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD "
                    "(default: last completed week)")
    ap.add_argument("--force-insert", action="store_true",
                    help="insert a new column even if this week's exists")
    ap.add_argument("--skip-download", action="store_true",
                    help="reuse the cached Tableau CSV (no live pull)")
    args = ap.parse_args()

    rep = _run(args)
    if args.dry_run:
        print("\n(dry-run — nothing written)")
    elif rep["unmatched"] or rep["ambiguous"]:
        print("\n✅ Filled — but review the ⚠ flags above.")
    else:
        print("\n✅ Done — column filled, total recomputed, owners sorted.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ Carlos Captainship Headcount FAILED: "
              f"{type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
