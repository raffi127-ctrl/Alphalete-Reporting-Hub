"""Combined Captainship Churn run — fills BOTH Captainship Churn tabs
(New Internet + Wireless) from a single Tableau patchright session.

Per Megan 2026-05-29: NO Slack post for Captainship. The sheet fill is
silent. Eve confirms visually after the run completes; the Local Office
sibling (`automations.churn.run`) is the one that posts the multi-week
PNG screenshots.

  python -m automations.captainship_churn.run
  python -m automations.captainship_churn.run --force-insert
  python -m automations.captainship_churn.run --dry-run
  python -m automations.captainship_churn.run --skip-download
  python -m automations.captainship_churn.run --only new-internet
  python -m automations.captainship_churn.run --only wireless
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.shared.tableau_patchright import tableau_session
from automations.captainship_churn import pull, fill


REPORTS = [
    # (slug, label, fetch_fn, open_ws_fn, csv_filename)
    ("new-internet", "Captainship New Internet Churn",
     pull.fetch_new_int, fill.open_ws_new_int,
     "captainship_new_int_churn.csv"),
    ("wireless",     "Captainship Wireless Churn",
     pull.fetch_wireless, fill.open_ws_wireless,
     "captainship_wireless_churn.csv"),
]


def _run_fill_phase(label: str, open_ws_fn, parsed: dict,
                    today: dt.date, args) -> int:
    """Fill one Captainship Churn tab. Returns 0 on success, 1 on
    early-exit (today's column already present without --force-insert)."""
    print(f"\n--- {label}: parse + fill ---")
    office = parsed["office_total"]
    reps = parsed["reps"]
    print(f"  ICDs with data: {len(reps)}")
    for p in pull.PERIODS:
        odata = office.get(p, {})
        units = pull.fmt_units(odata)
        print(f"    Captainship Avg {p:>4}-day: {odata.get('pct', '-'):>8}  "
              f"({units or '-'})")

    ws = open_ws_fn()
    sections = fill.find_sections(ws)
    for p, sect in sections.items():
        print(f"    {p:>4}-day: header row {sect['header_row']}, "
              f"{len(sect['rep_rows'])} existing ICDs")

    # Idempotency check FIRST so we don't insert missing reps into a
    # tab that's already filled for today — Megan may have manually
    # corrected the layout, and re-inserting would re-introduce blank
    # rows that she cleaned up.
    already_filled = fill.today_already_filled(ws, sections, today)
    skip_insert = already_filled and not args.force_insert
    if skip_insert:
        print(f"  ⚠ '{fill._date_label(today)}' already in B+C — skipping "
              f"INSERT (idempotent). write_today + cleanup pass still "
              f"runs so today's values get refreshed from the latest "
              f"pull (matters when the source URL changed mid-day, "
              f"e.g. Eve's wireless-URL fix 2026-05-29).")
    else:
        added = fill.insert_missing_reps(ws, sections, parsed,
                                         dry_run=args.dry_run, logfn=print)
        if added:
            for p, names in added.items():
                print(f"  + {p}-day: added {len(names)} new ICD(s): {names[:5]}"
                      + (" …" if len(names) > 5 else ""))
        else:
            print("  (no new ICDs to add)")
        if args.dry_run:
            print("  (dry-run, skipping column insert + merge)")
        else:
            fill.insert_two_cols_at_b(ws, sections)
            fill._merge_section_headers(ws, sections)

    # write_today runs every run — fresh values overwrite existing ones
    # so a re-run after a URL fix picks up the corrected pull.
    print(f"  Write today ({fill._date_label(today)})...")
    summary = fill.write_today(ws, sections, today, parsed,
                               dry_run=args.dry_run, logfn=print)
    for p, s in summary.items():
        unmatched_str = (f", {len(s['unmatched'])} unmatched"
                         if s['unmatched'] else "")
        print(f"    {p:>4}-day: {s['filled']} filled{unmatched_str}")

    # Cleanup pipeline — runs every run (including re-runs on the same
    # day) so today's formatting always reflects the latest code:
    #   unhide → sort → repaint pct colors → white-override units →
    #   hide blanks → clear empty-cell bg → hide 5-consec 0% pulls.
    fill.unhide_all_rep_rows(ws, sections,
                             dry_run=args.dry_run, logfn=print)
    fill.sort_sections_via_sortrange(ws, sections,
                                     dry_run=args.dry_run, logfn=print)
    fill.apply_pct_direct_colors(ws, sections, parsed,
                                 dry_run=args.dry_run, logfn=print)
    fill.apply_units_white_override(ws, sections,
                                    dry_run=args.dry_run, logfn=print)
    hide_actions = fill.hide_blanks_today(ws, sections,
                                          dry_run=args.dry_run, logfn=print)
    if isinstance(hide_actions, dict) and "hidden" in hide_actions:
        print(f"  Hidden: {len(hide_actions['hidden'])}   "
              f"Unhidden: {len(hide_actions['unhidden'])}")
    # Megan 2026-05-29: clear leftover bg on empty cells under each
    # section (was bleeding red/green/yellow into rows below the last
    # visible rep), repaint rep-row top+bottom borders (sortRange can
    # carry a no-border row into the visible block), then hide ICDs
    # that have been 0% for 5 consecutive pulls (not actionable to
    # track).
    fill.clear_empty_cell_backgrounds(ws, sections,
                                      dry_run=args.dry_run, logfn=print)
    fill.apply_rep_row_borders(ws, sections,
                               dry_run=args.dry_run, logfn=print)
    fill.hide_after_5_zero_pulls(ws, sections,
                                 dry_run=args.dry_run, logfn=print)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_churn")
    ap.add_argument("--date", default=None,
                    help="Override today's date (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen, but don't write to the Sheet.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse cached Tableau CSVs in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Insert a NEW B+C column even if today's date label "
                         "is already present.")
    ap.add_argument("--only", choices=("new-internet", "wireless"), default=None,
                    help="Run only one of the two reports.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    selected = [r for r in REPORTS if args.only is None or r[0] == args.only]

    print(f"=== Captainship Churn — {today.isoformat()} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    print(f"Reports: {[r[1] for r in selected]}")

    # --- Phase 1: pull both CSVs (single Tableau session) ---
    csvs: dict = {}
    if args.skip_download:
        for slug, label, _fetch_fn, _open_ws_fn, csv_name in selected:
            default = Path(tempfile.gettempdir()) / csv_name
            if not default.exists():
                print(f"  ⚠ --skip-download set but no cached CSV at {default}")
                return 1
            csvs[slug] = default
            print(f"  ✓ {label}: cached {default}")
    else:
        print("\nPhase 1: one Tableau patchright session, two Crosstab pulls...")
        with tableau_session(verbose=False) as page:
            for slug, label, fetch_fn, _open_ws_fn, _csv_name in selected:
                print(f"  → pulling {label}...")
                csvs[slug] = fetch_fn(verbose=False, page=page)
                print(f"    ✓ {csvs[slug]}")

    # --- Phase 2: parse + fill each ---
    print("\nPhase 2: fill destination tabs")
    for slug, label, _fetch_fn, open_ws_fn, _csv_name in selected:
        parsed = pull.parse(csvs[slug])
        _run_fill_phase(label, open_ws_fn, parsed, today, args)

    # No Slack post — Captainship is sheet-only (Megan 2026-05-29).

    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
