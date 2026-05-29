"""New Internet Churn — daily run (Raf's Local Office, Phase 1).

Pulls the ICD Churn Crosstab from the NewINTRafExpanded custom view
(pre-filtered to NEW INTERNET + ICD Owner Name = Rafael Hidalgo), then
fills the 'Local Office - New Internet Churn' tab on the AT&T Fiber
Metrics Report sheet for today.

  python -m automations.new_internet_churn.run                # today
  python -m automations.new_internet_churn.run --date 2026-05-28
  python -m automations.new_internet_churn.run --dry-run
  python -m automations.new_internet_churn.run --skip-download

Phase 2 (Captainship tab + Slack post) is intentionally NOT in this run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.new_internet_churn import pull, fill


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="new_internet_churn")
    ap.add_argument("--date", default=None,
                    help="Override today's date (YYYY-MM-DD). Default: today.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen, but don't write to Tableau output / Sheet.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the cached Tableau Crosstab CSV in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Insert a NEW B+C column even if today's date label is already "
                         "present in the leftmost data column. Default behavior is to "
                         "skip the run (idempotent) since the data's already filled.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    print(f"=== New Internet Churn — Local Office — {today.isoformat()} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")

    print("Step 1: Tableau ICD Churn pull (NewINTRafExpanded custom view)...")
    if args.skip_download:
        from pathlib import Path
        import tempfile
        csv_path = Path(tempfile.gettempdir()) / "new_internet_churn_local_office.csv"
        if not csv_path.exists():
            print(f"  ⚠ --skip-download passed but no cached CSV at {csv_path}")
            return 1
        print(f"  ✓ Reusing cached {csv_path}")
    else:
        csv_path = pull.fetch_crosstab(verbose=False)
        print(f"  ✓ {csv_path}")

    print("Step 2: Parse + pivot per-period data...")
    parsed = pull.parse(csv_path)
    office = parsed["office_total"]
    reps = parsed["reps"]
    print(f"  Reps with at least one period of data: {len(reps)}")
    for p in pull.PERIODS:
        odata = office.get(p, {})
        units = pull.fmt_units(odata)
        print(f"    Office {p:>4}-day: {odata.get('pct', '-'):>8}  ({units or '-'})")

    print(f"Step 3: Find section anchors on '{fill.TAB_LOCAL_OFFICE}'...")
    ws = fill.open_ws()
    sections = fill.find_sections(ws)
    for p, sect in sections.items():
        print(f"  {p:>4}-day: header row {sect['header_row']}, "
              f"{len(sect['rep_rows'])} existing reps in roster")

    print("Step 4: Insert missing reps (any rep in Tableau but not yet in section)...")
    added = fill.insert_missing_reps(ws, sections, parsed,
                                      dry_run=args.dry_run, logfn=print)
    if added:
        for p, names in added.items():
            print(f"  + {p}-day section: added {len(names)} rep(s): {names[:5]}"
                  + (" …" if len(names) > 5 else ""))
    else:
        print("  (no new reps to add)")

    already_filled = fill.today_already_filled(ws, sections, today)
    if already_filled and not args.force_insert:
        print(f"\n⚠ Today's column '{fill._date_label(today)}' already exists in "
              f"B+C — exiting early (idempotent). Re-run with --force-insert to "
              f"add a duplicate column anyway.")
        return 0

    print("Step 5: Insert 2 fresh date columns at B+C (sheet-wide)...")
    if args.dry_run:
        print("  (dry-run, skipping the column insert)")
    else:
        fill.insert_two_cols_at_b(ws, sections)

    print("Step 6: Merge section-header B+C cells (so date label spans both)...")
    if args.dry_run:
        print("  (dry-run, skipping merges)")
    else:
        fill._merge_section_headers(ws, sections)

    print(f"Step 7: Write today's data ({fill._date_label(today)})...")
    summary = fill.write_today(ws, sections, today, parsed,
                                dry_run=args.dry_run, logfn=print)
    for p, s in summary.items():
        print(f"  {p:>4}-day: {s['filled']} filled"
              + (f", {len(s['unmatched'])} unmatched (rep has data but no roster row): "
                 f"{s['unmatched'][:5]}"
                 + (" …" if len(s['unmatched']) > 5 else "")
                 if s['unmatched'] else ""))

    print("Step 8: Sort each section by today's % descending (blanks sink to bottom)...")
    fill.sort_sections_desc(ws, sections, dry_run=args.dry_run, logfn=print)

    print("Step 9: Hide rep rows with no data today; unhide rows that have data...")
    hide_actions = fill.hide_blanks_today(ws, sections,
                                          dry_run=args.dry_run, logfn=print)
    if isinstance(hide_actions, dict) and "hidden" in hide_actions:
        print(f"  Hidden: {len(hide_actions['hidden'])}   "
              f"Unhidden: {len(hide_actions['unhidden'])}")

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
