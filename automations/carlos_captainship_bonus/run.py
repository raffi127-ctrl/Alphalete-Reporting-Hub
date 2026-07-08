"""Carlos B2B Captainship Bonus — weekly hub run.

Inserts a fresh week column on the "Carlos B2B Captainship" tab of the
*All In One - CARLOS* sheet, fills each active rep's Total Activations for
Carlos' B2B team (Tableau ATTTRACKER-B2B / Captain Team, current cycle), sets
the four metric cells (team 0-30 churn %, personal 0-30 churn %, 31-60
activation %, non-payment %), lets the Total Activations / Money Made / TOTAL
AMOUNT formulas recompute, re-points the chart's series at the Total - All
Units row, and exports the 5-week + chart view to
~/Downloads/Carlos Captainship Weekending <M.D>.pdf.

Idempotent: re-running the same week refreshes in place (--force-insert to
override).

  python -m automations.carlos_captainship_bonus.run
  python -m automations.carlos_captainship_bonus.run --dry-run
  python -m automations.carlos_captainship_bonus.run --tab "Copy of Carlos B2B Captainship"
  python -m automations.carlos_captainship_bonus.run --week 2026-07-05 --skip-download --no-pdf
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

REPORT_ID = "carlos_captainship_bonus"


def _current_we_sunday(today: dt.date | None = None) -> dt.date:
    from automations.fiber_activations import pull as P
    return P.cycle_sunday(today or dt.date.today())


def _run(args) -> dict:
    if args.tab:
        os.environ["CCB_TAB"] = args.tab
    from automations.carlos_captainship_bonus import sheet_fill, tableau_pull, pdf_export

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    we = dt.date.fromisoformat(args.week) if args.week else _current_we_sunday(today)
    label = sheet_fill.week_label(we)
    print(f"Carlos B2B Captainship → week ending {we} (col '{label}') · "
          f"tab '{sheet_fill.TAB}' · {'DRY-RUN' if args.dry_run else 'LIVE'}",
          flush=True)

    if args.skip_download:
        pull = tableau_pull.parse_cached()
        src = "cached"
    else:
        pull = tableau_pull.pull_carlos(today, verbose=True)
        src = "pulled"
    print(f"  Tableau ({src}): {len(pull.reps)} Carlos reps, team total "
          f"{pull.grand_total}, churn(team) {pull.churn_team}, churn(Carlos) "
          f"{pull.churn_personal}, activation {pull.activation}, non-pmt "
          f"{pull.nonpmt}", flush=True)
    if not pull.reps:
        raise RuntimeError("Tableau returned no Carlos reps — aborting.")

    ws, sh = sheet_fill.open_tab()
    rep = sheet_fill.run_fill(ws, sh, pull, we, dry_run=args.dry_run,
                              force_insert=args.force_insert,
                              auto_roster=not args.no_roster)

    verb_add = "will add" if args.dry_run else "added"
    verb_hide = "will hide" if args.dry_run else "hid"
    print("\n=== " + ("PLAN" if args.dry_run else "RESULT") + " ===", flush=True)
    for line in rep["log"]:
        print(line if line.startswith("  ") else "  " + line, flush=True)
    print(f"\n  Total Activations {rep['label']} = {rep['total']}  "
          f"({len(rep['matched'])} reps)", flush=True)
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

    rep["pdf"] = None
    if not args.dry_run and not args.no_pdf:
        out = Path(args.pdf_dir).expanduser() / pdf_export.default_name(we)
        pdf_export.export_pdf(sheet_fill.SPREADSHEET_ID, ws.id, out)
        rep["pdf"] = str(out)
        print(f"\n  📄 PDF → {out}", flush=True)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Carlos B2B Captainship Bonus")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD (default last week)")
    ap.add_argument("--today", help="override 'today' YYYY-MM-DD (drives the "
                    "Tableau Weekending filter)")
    ap.add_argument("--tab", help="target tab (default 'Carlos B2B Captainship'; "
                    "use 'Copy of Carlos B2B Captainship' to test)")
    ap.add_argument("--force-insert", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--pdf-dir", default="~/Downloads")
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
        print(f"\n❌ Carlos B2B Captainship FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
