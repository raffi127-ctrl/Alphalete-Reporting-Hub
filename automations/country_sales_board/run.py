#!/usr/bin/env python3
"""Country Sales Board — daily fill.

Fills the 'Country Sales Board' tab of the ATT Program - Focus Report workbook
from the D2D1-PAGERV4 Tableau view. One crosstab in, seven day columns out; the
rest of the tab is formulas that recompute themselves (see fill.py).

  python -m automations.country_sales_board.run                 # sandbox, live write
  python -m automations.country_sales_board.run --dry-run       # plan only
  python -m automations.country_sales_board.run --last-week     # fill from the (LW2) sheet
  python -m automations.country_sales_board.run --from-csv P    # offline, no browser
  python -m automations.country_sales_board.run --real          # PROD tab (guarded)

SANDBOX BY DEFAULT. `--real` targets the live tab the VAs read and is refused
unless paired with `--i-mean-it`, mirroring org_sales_board's guard.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_sales_board.fill_section import apply_plan
from automations.country_sales_board import fill as cf, pull as cp

SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
PROD_TAB = "Country Sales Board"
SANDBOX_TAB = "Country Sales Board (sandbox)"
OUT_DIR = Path("output")


def main() -> int:
    ap = argparse.ArgumentParser(description="Country Sales Board daily fill")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan and print the writes; touch nothing.")
    ap.add_argument("--real", action="store_true",
                    help=f"Target {PROD_TAB!r} instead of the sandbox tab.")
    ap.add_argument("--i-mean-it", action="store_true",
                    help="Required alongside --real (writing the live tab).")
    ap.add_argument("--last-week", action="store_true",
                    help="Pull the (LW2) worksheet — the week before the "
                         "view's current one.")
    ap.add_argument("--from-csv", metavar="PATH",
                    help="Parse an already-downloaded crosstab instead of "
                         "opening Tableau (offline engine check).")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="Override today's date (testing/backfill).")
    args = ap.parse_args()

    if args.real and not args.i_mean_it:
        print(f"refusing to write {PROD_TAB!r} without --i-mean-it. "
              f"Build against the sandbox first.")
        return 2
    today = (dt.date.fromisoformat(args.today) if args.today else dt.date.today())
    tab = PROD_TAB if args.real else SANDBOX_TAB
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== Country Sales Board — {tab!r} — {mode} — today={today} ===")

    # ---- pull ----
    if args.from_csv:
        from automations.org_sales_board import section_pull as sp
        print(f"  parsing {args.from_csv} (offline)…")
        pull = sp.parse_crosstab_byday(cp.SPEC, Path(args.from_csv), today)
        print(f"  parsed {len(pull)} ICD owner(s)")
    else:
        from automations.shared.tableau_patchright import tableau_session
        try:
            with tableau_session() as page:
                pull = cp.pull_icd_days(page, OUT_DIR, last_week=args.last_week,
                                        today=today)
        except cp.NoDataYet as e:
            # Not a failure: Tableau hides an empty worksheet, so this is the
            # normal state before the week's first sales land.
            print(f"  ⏸ {e}")
            print("=== nothing to fill yet — done ===")
            return 0

    # ---- plan ----
    ws = open_by_key(SHEET_ID).worksheet(tab)
    grid = _retry(ws.get_all_values)

    # A rep appended at the BOTTOM of the day block is filled but falls outside
    # the tab's fixed =SUMIF/=SUM ranges, so they'd count toward nothing. Say so
    # before writing rather than let the board quietly under-report.
    fgrid = _retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
    for line in cf.audit_aggregate_coverage(fgrid, grid):
        print(line)

    plan = cf.plan_day_fill(grid, pull, today=today)
    if not plan.updates:
        for line in plan.log:      # apply_plan prints the log; short-circuit here
            print(line)
        print("=== no writes planned — done ===")
        return 0

    # ---- apply ----
    apply_plan(ws, plan, dry_run=args.dry_run)
    print(f"=== {len(plan.updates)} cell write(s) "
          f"{'planned' if args.dry_run else 'applied'} — done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
