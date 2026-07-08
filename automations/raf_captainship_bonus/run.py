"""Raf Captainship Bonus — weekly hub run.

Inserts a fresh week column on the "Captainship Bonuses" tab of the
*Alphalete Org/Captainship Reports* sheet, fills each active rep's Total
Activations for Raf's team (Tableau CaptainsBonus, current cycle), sets the
team New Internet 60-day Churn % + Activation % (Rolling 4 Weeks), lets the
Total Sales / Money Made / TOTAL MONEY MADE formulas recompute, re-points the
performance chart's series at the Total Sales row, and exports the 4-week +
chart view to ~/Downloads/RafCaptainship <M.D>.pdf.

Idempotent: if this week's column already exists it refreshes in place
(override with --force-insert).

  python -m automations.raf_captainship_bonus.run
  python -m automations.raf_captainship_bonus.run --dry-run
  python -m automations.raf_captainship_bonus.run --week 2026-07-05
  python -m automations.raf_captainship_bonus.run --tab "Copy of Captainship Bonuses"
  python -m automations.raf_captainship_bonus.run --force-insert --skip-download --no-pdf
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

REPORT_ID = "raf_captainship_bonus"


def _current_we_sunday(today: dt.date | None = None) -> dt.date:
    """Sunday of the last completed week (matches the sheet's WE column)."""
    from automations.fiber_activations import pull as P
    today = today or dt.date.today()
    return P.cycle_sunday(today)


def _run(args) -> dict:
    if args.tab:
        os.environ["RCB_TAB"] = args.tab
    from automations.raf_captainship_bonus import sheet_fill, tableau_pull, pdf_export

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    we = dt.date.fromisoformat(args.week) if args.week else _current_we_sunday(today)
    label = sheet_fill.week_label(we)
    print(f"Raf Captainship Bonus → week ending {we} (col '{label}') · "
          f"tab '{sheet_fill.TAB}' · {'DRY-RUN' if args.dry_run else 'LIVE'}",
          flush=True)

    # 1) Tableau pull (per-rep Total Activations + team churn/rolling).
    if args.skip_download:
        pull = tableau_pull.parse_cached()
        print(f"  Tableau (cached): {len(pull.reps)} Raf reps, "
              f"grand {pull.grand_total}, churn {pull.churn}, "
              f"activation {pull.rolling}", flush=True)
    else:
        pull = tableau_pull.pull_raf(today, verbose=True)
        print(f"  Tableau: {len(pull.reps)} Raf reps pulled, "
              f"grand {pull.grand_total}, churn {pull.churn}, "
              f"activation {pull.rolling}", flush=True)
    if not pull.reps:
        raise RuntimeError("Tableau returned no Raf reps — aborting.")

    # 2) Fill the sheet.
    ws, sh = sheet_fill.open_tab()
    rep = sheet_fill.run_fill(ws, sh, pull, we, dry_run=args.dry_run,
                              force_insert=args.force_insert,
                              auto_roster=not args.no_roster)

    verb_add = "will add" if args.dry_run else "added"
    verb_hide = "will hide" if args.dry_run else "hid"
    print("\n=== " + ("PLAN" if args.dry_run else "RESULT") + " ===", flush=True)
    for line in rep["log"]:
        print(line if line.startswith("  ") else "  " + line, flush=True)
    print(f"\n  Total Sales {rep['label']} = {rep['total']}  "
          f"({len(rep['matched'])} reps)  · churn {rep['churn']} · "
          f"activation {rep['rolling']}", flush=True)
    if rep["ambiguous"]:
        print("  ⚠ AMBIGUOUS (pin in sheet_fill.ALIASES): "
              + "; ".join(rep["ambiguous"]), flush=True)
    if not args.no_roster:
        if rep["new_reps"]:
            print(f"  ➕ New rep(s) {verb_add} (Tableau roster, no sheet row): "
                  + ", ".join(f"{n} ({v})" for n, v in rep["new_reps"]), flush=True)
        if rep["hidden_departed"]:
            print(f"  ➖ Departed rep(s) {verb_hide} (off the Tableau roster): "
                  + ", ".join(rep["hidden_departed"]), flush=True)
    elif rep["unmatched"]:
        print("  ⚠ ACTIVE rep NOT in Tableau (roster off — handle manually): "
              + ", ".join(rep["unmatched"]), flush=True)

    # 3) PDF (skip on dry-run or --no-pdf).
    rep["pdf"] = None
    if not args.dry_run and not args.no_pdf:
        out = Path(args.pdf_dir).expanduser() / pdf_export.default_name(we)
        pdf_export.export_pdf(sheet_fill.SPREADSHEET_ID, ws.id, out)
        rep["pdf"] = str(out)
        print(f"\n  📄 PDF → {out}", flush=True)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Raf Captainship Bonus")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + match + show the plan, write nothing")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD (default: last "
                    "completed week)")
    ap.add_argument("--today", help="override 'today' YYYY-MM-DD (drives the "
                    "Tableau Weekending filter)")
    ap.add_argument("--tab", help="target tab (default 'Captainship Bonuses'; "
                    "use 'Copy of Captainship Bonuses' to test)")
    ap.add_argument("--force-insert", action="store_true",
                    help="insert a new column even if this week's exists")
    ap.add_argument("--skip-download", action="store_true",
                    help="reuse the cached Tableau CSVs (no live pull)")
    ap.add_argument("--no-pdf", action="store_true", help="skip the PDF export")
    ap.add_argument("--pdf-dir", default="~/Downloads",
                    help="where to write the PDF (default ~/Downloads)")
    ap.add_argument("--no-roster", action="store_true",
                    help="don't auto add/hide rows for roster changes (just flag them)")
    args = ap.parse_args()

    rep = _run(args)
    if args.dry_run:
        print("\n(dry-run — nothing written)")
    elif rep["ambiguous"] or (args.no_roster and rep["unmatched"]):
        print("\n✅ Filled — but review the ⚠ flags above.")
    elif rep["new_reps"] or rep["hidden_departed"]:
        print("\n✅ Done — column filled, roster synced (see ➕/➖ above), "
              "chart re-pointed.")
    else:
        print("\n✅ Done — column filled, formulas recomputed, chart re-pointed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ Raf Captainship Bonus FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
