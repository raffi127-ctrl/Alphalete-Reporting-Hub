"""Alphalete ORG Sales Board — build steps (work in progress).

Multi-section board on the 'Alphalete ORG Sales Board' tab. Being built
section by section from Megan's walkthrough videos; practice on the duplicated
'Copy of Alphalete ORG Sales Board' tab until told to point at the real one.

Sections (top to bottom):
  1. Product Summary - This Week   (Product Type x Mon-Sun + Grand Total)
  2. RAF ORG - Current vs Prior Weeks
  3. ICD leaderboard by campaign x week-ending columns
  4. CAPTAIN TEAM rollups
  5. historical week-list

CORRECTION (2026-05-30): the Product Summary AND the RAF ORG vs-Prior tables are
FORMULA-DRIVEN — they auto-derive from the daily sections (Product Summary pulls
each section's Totals row: `=C85`, `=C103`, …; Grand Total `=SUM`; RAF ORG
references section history rows). They must NOT be cleared/hardcoded. The
new-week reset belongs on the daily SECTION fill areas + the section-history
shift, not here. `clear_product_summary` below is SUPERSEDED and guarded off.
See workflows/org-sales-board-recipe.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
SANDBOX_TAB = "Copy of Alphalete ORG Sales Board"
PROD_TAB = "Alphalete ORG Sales Board"          # real tab — only when told

OUT_DIR = Path("output")                         # one-off CSVs land here

SUMMARY_TITLE = "Product Summary - This Week"
SUMMARY_END = "RAF ORG"                          # next section (prefix match)
HEADER_LABEL = "Product Type"                    # day-header rows in the section
GRAND_TOTAL_HDR = "Grand Total"


def _col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _find(colB, pred, start=1):
    for i in range(start, len(colB) + 1):
        if pred((colB[i - 1] or "").strip()):
            return i
    return None


def clear_product_summary(ws, *, dry_run=False, logfn=print):
    """SUPERSEDED — the Product Summary is formula-driven (auto-pulls each
    daily section's Totals row); clearing it would wipe live formulas. Kept
    only for reference; guarded off. Label-anchored clear logic is reusable
    for the daily SECTION fill areas later."""
    raise RuntimeError(
        "clear_product_summary is retired: the Product Summary is "
        "formula-driven and must not be cleared. The new-week reset belongs on "
        "the daily section fill areas + history shift (see recipe)."
    )
    colB = ws.col_values(2)  # noqa: unreachable — retained for reuse
    r_title = _find(colB, lambda v: v.lower() == SUMMARY_TITLE.lower())
    if not r_title:
        raise ValueError(f"Couldn't find '{SUMMARY_TITLE}' in column B.")
    r_end = _find(colB, lambda v: v.upper().startswith(SUMMARY_END.upper()),
                  start=r_title + 1) or (len(colB) + 1)

    # data-column span from a header row (B='Product Type' .. 'Grand Total')
    r_hdr = _find(colB, lambda v: v.lower() == HEADER_LABEL.lower(),
                  start=r_title)
    hdr = ws.row_values(r_hdr)
    first_col = 3                                  # col C — first day, right of B
    gt_col = next((i + 1 for i, c in enumerate(hdr)
                   if c.strip().lower() == GRAND_TOTAL_HDR.lower()), 10)

    # data rows: labelled, not a header, within the section
    data_rows = [r for r in range(r_title + 1, r_end)
                 if (colB[r - 1] or "").strip()
                 and (colB[r - 1] or "").strip().lower() != HEADER_LABEL.lower()
                 and (colB[r - 1] or "").strip().lower() != SUMMARY_TITLE.lower()]

    # contiguous runs -> one clear range each (skips interior header rows)
    runs, run = [], []
    for r in data_rows:
        if run and r == run[-1] + 1:
            run.append(r)
        else:
            if run:
                runs.append(run)
            run = [r]
    if run:
        runs.append(run)
    ranges = [f"{_col(first_col)}{run[0]}:{_col(gt_col)}{run[-1]}" for run in runs]

    logfn(f"  Product Summary: rows {data_rows[0]}-{data_rows[-1]} "
          f"({len(data_rows)} data rows), cols {_col(first_col)}-{_col(gt_col)}")
    logfn(f"  clear ranges: {ranges}")
    if dry_run:
        logfn("  (dry-run — nothing cleared)")
        return ranges
    ws.batch_clear(ranges)
    logfn(f"  cleared {len(ranges)} range(s) ✓")
    return ranges


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_sales_board")
    ap.add_argument("--step", default="daily",
                    choices=["clear-summary", "retail-nl", "daily",
                             "captainships", "rollover"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--real", action="store_true",
                    help="Target the REAL tab instead of the sandbox copy.")
    ap.add_argument("--from-csv",
                    help="Parse a saved SARA by-day CSV instead of pulling "
                         "live (offline engine validation).")
    ap.add_argument("--with-captainships", action="store_true",
                    help="On the 'daily' step, also fill the 10 captainship "
                         "leaderboards in the SAME login (one full-board run).")
    args = ap.parse_args(argv)

    tab = PROD_TAB if args.real else SANDBOX_TAB
    print(f"=== ORG Sales Board — {args.step} — tab={tab!r} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    ws = open_by_key(SHEET_ID).worksheet(tab)
    if args.step == "clear-summary":
        clear_product_summary(ws, dry_run=args.dry_run)
    elif args.step == "rollover":
        # Monday freeze: shift each leaderboard's current week into history
        # (grow a column), freeze each delta table's "this week" -> "last
        # week", then blank the daily day-cells for the fresh week.
        from automations.org_sales_board import rollover
        rollover.run_rollover(ws, dry_run=args.dry_run)
    elif args.step == "captainships":
        # All 10 captainships under ONE patchright session: each captain's
        # TEAM view + org-wide all-products fallback, filled worksheet-scoped.
        from automations.org_sales_board import captainship
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=False) as page:
            captainship.run_captainships(ws, page, dry_run=args.dry_run)
    else:
        # Both 'daily' (all sections) and 'retail-nl' (just the SARA pair)
        # run through the ONE patchright-session orchestrator — no CDP.
        from automations.org_sales_board import orchestrate
        only = (["Retail NL", "Retail Internet"]
                if args.step == "retail-nl" else None)
        from_csv = Path(args.from_csv) if args.from_csv else None
        # On TUESDAY the full daily run rolls the week over FIRST (Megan
        # 2026-06-03: no separate card — it's folded into the Tuesday run).
        # run_rollover self-guards (skips if already done this week), so it's
        # safe to re-run. Pure sheet ops — no Tableau session needed.
        import datetime as _dt
        if args.step == "daily" and _dt.date.today().weekday() == 1:
            from automations.org_sales_board import rollover
            print("--- Tuesday: weekly rollover first ---")
            rollover.run_rollover(ws, dry_run=args.dry_run)
        orchestrate.run_daily(ws, dry_run=args.dry_run, only=only,
                              from_csv=from_csv,
                              include_captainships=args.with_captainships)
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
