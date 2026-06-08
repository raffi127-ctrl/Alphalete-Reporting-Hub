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
from automations.focus_office_att.aliases import load_aliases, alias_to_canonical


REPORTS = [
    # (slug, label, fetch_fn, open_ws_fn, csv_filename)
    ("new-internet", "Captainship New Internet Churn",
     pull.fetch_new_int, fill.open_ws_new_int,
     "captainship_new_int_churn.csv"),
    ("wireless",     "Captainship Wireless Churn",
     pull.fetch_wireless, fill.open_ws_wireless,
     "captainship_wireless_churn.csv"),
]


def _apply_aliases(parsed: dict, aliases: dict) -> dict:
    """Map every parsed rep name through the ICD Aliases sheet to its
    canonical sheet-tab name BEFORE the fill, so a Tableau spelling that
    differs from the sheet (e.g. 'Muhammad Haque' -> 'Hammad Haque') matches
    the existing row instead of inserting a duplicate. Mirrors
    owners_metrics_churn.run; captainship previously had NO alias step, which
    is why Hammad/Muhammad Haque, Josep/Joseph Logan, Aya Al-Khafaji/Alkhafaji
    and Tony Chavez/Jose Antonio Chavez ended up duplicated on Raf's
    Captainship (Eve 2026-06-02)."""
    if not aliases:
        return parsed
    new_reps: dict = {}
    for name, periods in parsed.get("reps", {}).items():
        canonical = alias_to_canonical(name, aliases)
        if canonical in new_reps:
            # Merge same-period slots if both spellings carried data.
            for p, slot in periods.items():
                new_reps[canonical].setdefault(p, {}).update(slot)
        else:
            new_reps[canonical] = periods
    parsed["reps"] = new_reps
    return parsed


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
              f"COLUMN insert (idempotent). insert_missing_reps + "
              f"write_today + cleanup still run so today's values get "
              f"refreshed from the latest pull (matters when the source "
              f"URL changed mid-day, e.g. Eve's wireless-URL fix "
              f"2026-05-29).")
    # insert_missing_reps runs EVERY run, including same-day refreshes
    # (Megan 2026-06-04): a row that goes missing after the day's first
    # fill (e.g. deleted in a manual dup cleanup — Jairo Ruiz 60-day /
    # Drew Tepper 90-day on the Owners tabs) was never re-created
    # because the insert only ran on the first run of the day.
    added = fill.insert_missing_reps(ws, sections, parsed,
                                     dry_run=args.dry_run, logfn=print)
    if added:
        for p, names in added.items():
            print(f"  + {p}-day: added {len(names)} new ICD(s): {names[:5]}"
                  + (" …" if len(names) > 5 else ""))
    else:
        print("  (no new ICDs to add)")
    if not skip_insert:
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
    # carry a no-border row into the visible block).
    # NOTE: hide_after_5_zero_pulls was REMOVED from this pipeline
    # (Megan 2026-06-04 visibility rule): 0% is data — show the rep.
    # Only reps with NO pct this bucket are hidden (hide_blanks_today).
    fill.clear_empty_cell_backgrounds(ws, sections,
                                      dry_run=args.dry_run, logfn=print)
    fill.apply_rep_row_borders(ws, sections,
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
    failed: list = []
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
                # SELF-HEAL + RESILIENCE (Megan 2026-06-08): retry once before
                # skipping, and never let one pull's failure crash the run.
                # Most failures are a transient slow/flaky Tableau load; a
                # genuinely corrupted view fails both attempts → skip + flag.
                last_err = None
                for attempt in (1, 2):
                    try:
                        csvs[slug] = fetch_fn(verbose=False, page=page)
                        print(f"    ✓ {csvs[slug]}")
                        last_err = None
                        break
                    except Exception as e:
                        last_err = e
                        if attempt == 1:
                            print(f"    ⚠ {label}: pull attempt 1 failed "
                                  f"({str(e).splitlines()[0][:80]}) — retrying once…")
                if last_err is not None:
                    print(f"    ⚠ {label}: pull FAILED after retry — skipping "
                          f"(the rest continue). {str(last_err).splitlines()[0][:160]}")
                    failed.append(label)

    # --- Phase 2: parse + fill each ---
    # Load ICD aliases once and canonicalize every parsed rep name BEFORE the
    # fill, so a Tableau spelling that differs from the sheet matches the
    # existing row instead of inserting a duplicate (mirrors owners_metrics).
    print("\nPhase 2: fill destination tabs")
    aliases = load_aliases()
    if aliases:
        print(f"  Loaded {sum(len(v) for v in aliases.values())} aliases "
              f"({len(aliases)} canonical names).")
    for slug, label, _fetch_fn, open_ws_fn, _csv_name in selected:
        if slug not in csvs:
            continue   # pull failed/skipped above — already flagged
        parsed = pull.parse(csvs[slug])
        parsed = _apply_aliases(parsed, aliases)
        _run_fill_phase(label, open_ws_fn, parsed, today, args)

    # No Slack post — Captainship is sheet-only (Megan 2026-05-29).

    if failed:
        # NEVER read 'done' when data is missing (Megan 2026-06-08). No 'done'
        # wording on this path so the Hub doesn't mark it completed.
        print(f"\n=== run INCOMPLETE — NOT marking complete. "
              f"{len(selected) - len(failed)}/{len(selected)} filled; "
              f"MISSING {len(failed)}: {failed} ===")
        print("  Usually a flaky/slow Tableau load (often clears on a re-run) "
              "or a corrupted custom view (re-create it). The healthy tab(s) "
              "ARE filled.")
        return 1
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
