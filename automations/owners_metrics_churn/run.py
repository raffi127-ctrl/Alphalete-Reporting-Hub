"""Combined runner for the Owners Metrics Report churn tabs.

Phase 1 (Fiber): pulls Wayne / Starr Rodenhurst / Aron Corral —
one Tableau patchright session, three Crosstab downloads, three
sheet fills. Sheet-only (no Slack post). All three tabs share the
same column / section layout (CHURN TIERS at rows 1-3, captain name
at row 7, sections from row 8 with 0-30 / 30 / 60 / 90 buckets).

Phases 2 (B2B) and 3 (NDS) plug in as additional REPORTS entries
when megan sends those URLs.

  python -m automations.owners_metrics_churn.run
  python -m automations.owners_metrics_churn.run --force-insert
  python -m automations.owners_metrics_churn.run --dry-run
  python -m automations.owners_metrics_churn.run --skip-download
  python -m automations.owners_metrics_churn.run --only wayne
  python -m automations.owners_metrics_churn.run --only wayne,starr
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.shared.tableau_patchright import tableau_session
from automations.owners_metrics_churn import pull, fill
from automations.focus_office_att.aliases import load_aliases, alias_to_canonical


def _apply_aliases(parsed: dict, aliases: dict) -> dict:
    """Post-process a parsed dict: map every rep name through the
    aliases sheet so the runner's downstream matching against the
    destination tab uses the canonical sheet-tab name.

    If two parsed names collapse to the same canonical (e.g. both
    'Mohammad' and 'Mohammed' map to 'Mohammad Altom'), merge their
    period slots. Megan 2026-05-29: 'Mohammed Altom' (sheet) vs
    'Mohammad Altom' (Tableau) created a duplicate insert on
    Khalil's NDS tab — wiring the alias dict here prevents it.
    """
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


REPORTS = [
    # (slug, label, fetch_fn, open_ws_fn, csv_filename, parse_fn, periods)
    # ----- ATT Fiber (Phase 1) -----
    ("wayne", "Wayne (ATT Fiber)",
     pull.fetch_fiber_wayne, fill.open_ws_fiber_wayne,
     "owners_fiber_wayne.csv", pull.parse, pull.PERIODS),
    ("starr", "Starr Rodenhurst (ATT Fiber)",
     pull.fetch_fiber_starr, fill.open_ws_fiber_starr,
     "owners_fiber_starr.csv", pull.parse, pull.PERIODS),
    ("aron", "Aron Corral (ATT Fiber)",
     pull.fetch_fiber_aron, fill.open_ws_fiber_aron,
     "owners_fiber_aron.csv", pull.parse, pull.PERIODS),
    # ----- B2B (Phase 2) -----
    ("carlos", "Carlos Hidalgo (B2B)",
     pull.fetch_b2b_carlos, fill.open_ws_b2b_carlos,
     "owners_b2b_carlos.csv", pull.parse_b2b, pull.B2B_PERIODS),
    ("eveliz", "Eveliz Wright (B2B)",
     pull.fetch_b2b_eveliz, fill.open_ws_b2b_eveliz,
     "owners_b2b_eveliz.csv", pull.parse_b2b, pull.B2B_PERIODS),
    ("luis", "Luis Salazar (B2B)",
     pull.fetch_b2b_luis, fill.open_ws_b2b_luis,
     "owners_b2b_luis.csv", pull.parse_b2b, pull.B2B_PERIODS),
    # ----- NDS (Phase 3) -----
    ("khalil", "Khalil Mansour (NDS)",
     pull.fetch_nds_khalil, fill.open_ws_nds_khalil,
     "owners_nds_khalil.csv", pull.parse_nds, pull.NDS_PERIODS),
    ("colten", "Colten Wright (NDS)",
     pull.fetch_nds_colten, fill.open_ws_nds_colten,
     "owners_nds_colten.csv", pull.parse_nds, pull.NDS_PERIODS),
    ("jairo", "Jairo Ruiz (NDS)",
     pull.fetch_nds_jairo, fill.open_ws_nds_jairo,
     "owners_nds_jairo.csv", pull.parse_nds, pull.NDS_PERIODS),
]


def _run_fill_phase(label: str, open_ws_fn, parsed: dict, periods: tuple,
                    today: dt.date, args) -> int:
    """Fill one tab. Returns 0 on success, 1 on early-exit when
    today is already in place AND --force-insert wasn't set."""
    print(f"\n--- {label}: parse + fill ---")
    office = parsed["office_total"]
    reps = parsed["reps"]
    print(f"  ICDs with data: {len(reps)}")
    for p in periods:
        odata = office.get(p, {})
        units = pull.fmt_units(odata)
        print(f"    Captainship Avg {p:>4}-day: {odata.get('pct', '-'):>8}  "
              f"({units or '-'})")

    ws = open_ws_fn()
    sections = fill.find_sections(ws)
    for p, sect in sections.items():
        print(f"    {p:>4}-day: header row {sect['header_row']}, "
              f"{len(sect['rep_rows'])} existing ICDs")

    already_filled = fill.today_already_filled(ws, sections, today)
    skip_insert = already_filled and not args.force_insert
    if skip_insert:
        print(f"  ⚠ '{fill._date_label(today)}' already in B+C — skipping "
              f"COLUMN insert (idempotent). insert_missing_reps + "
              f"write_today + cleanup still run so today's values get "
              f"refreshed from the latest pull.")
    # insert_missing_reps runs EVERY run, including same-day refreshes
    # (Megan 2026-06-04): a row that goes missing after the day's first
    # fill (Jairo Ruiz 60-day / Drew Tepper 90-day, deleted in a manual
    # dup cleanup) was never re-created because the insert only ran on
    # the first run of the day.
    added = fill.insert_missing_reps(ws, sections, parsed,
                                     dry_run=args.dry_run, logfn=print)
    if added:
        for p, names in added.items():
            print(f"  + {p}-day: added {len(names)} new ICD(s): "
                  f"{names[:5]}" + (" …" if len(names) > 5 else ""))
    else:
        print("  (no new ICDs to add)")
    if not skip_insert:
        if args.dry_run:
            print("  (dry-run, skipping column insert + merge)")
        else:
            fill.insert_two_cols_at_b(ws, sections)
            fill._merge_section_headers(ws, sections)

    print(f"  Write today ({fill._date_label(today)})...")
    summary = fill.write_today(ws, sections, today, parsed,
                               dry_run=args.dry_run, logfn=print)
    for p, s in summary.items():
        unmatched_str = (f", {len(s['unmatched'])} unmatched"
                         if s['unmatched'] else "")
        print(f"    {p:>4}-day: {s['filled']} filled{unmatched_str}")

    # Cleanup pipeline — same order as Captainship + Local Office.
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
    fill.clear_empty_cell_backgrounds(ws, sections,
                                      dry_run=args.dry_run, logfn=print)
    fill.apply_rep_row_borders(ws, sections,
                               dry_run=args.dry_run, logfn=print)
    # hide_after_5_zero_pulls REMOVED (Megan 2026-06-04 visibility
    # rule): 0% is data — show the rep. Only reps with NO pct this
    # bucket stay hidden (hide_blanks_today).
    return 0


def _parse_only(arg: str | None) -> set[str] | None:
    if not arg:
        return None
    return {s.strip().lower() for s in arg.split(",") if s.strip()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="owners_metrics_churn")
    ap.add_argument("--date", default=None,
                    help="Override today's date (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen, but don't write.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse cached Tableau CSVs in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Insert a NEW B+C column even if today's date "
                         "label is already present.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated slugs to run. Fiber: wayne, "
                         "starr, aron. B2B: carlos, eveliz. NDS: khalil, "
                         "colten, jairo. Defaults to all.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    only = _parse_only(args.only)
    selected = [r for r in REPORTS if only is None or r[0] in only]
    if not selected:
        print(f"No reports match --only={args.only}. "
              f"Valid slugs: {[r[0] for r in REPORTS]}")
        return 1

    print(f"=== Owners Metrics Churn — {today.isoformat()} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    print(f"Reports: {[r[1] for r in selected]}")

    # --- Phase 1: pull each CSV (shared Tableau session) ---
    csvs: dict = {}
    failed: list = []
    if args.skip_download:
        for slug, label, _fetch_fn, _open_ws_fn, csv_name, _parse_fn, _periods in selected:
            default = Path(tempfile.gettempdir()) / csv_name
            if not default.exists():
                print(f"  ⚠ --skip-download set but no cached CSV at {default}")
                return 1
            csvs[slug] = default
            print(f"  ✓ {label}: cached {default}")
    else:
        print(f"\nPhase 1: one Tableau session, {len(selected)} Crosstab pull(s)...")
        with tableau_session(verbose=False) as page:
            for slug, label, fetch_fn, _open_ws_fn, _csv_name, _parse_fn, _periods in selected:
                print(f"  → pulling {label}...")
                try:
                    csvs[slug] = fetch_fn(verbose=False, page=page)
                    print(f"    ✓ {csvs[slug]}")
                except Exception as e:
                    # One captain's pull failing — e.g. a corrupted Tableau
                    # custom view ("Couldn't find the 'ICD Churn' sheet…") —
                    # must NOT kill the other captainships. Skip + flag it; the
                    # rest still pull and fill (Eve glitch 2026-06-05).
                    msg = str(e).splitlines()[0][:160]
                    print(f"    ⚠ {label}: pull FAILED — skipping (the rest "
                          f"continue). {msg}")
                    failed.append(label)

    # --- Phase 2: parse + fill each ---
    # Load aliases once per run — applied to every parser's output so
    # name-spelling drift between Tableau + the sheet (Mohammad vs
    # Mohammed Altom etc.) doesn't insert duplicate ICDs.
    print("\nPhase 2: fill destination tabs")
    aliases = load_aliases()
    if aliases:
        print(f"  Loaded {sum(len(v) for v in aliases.values())} aliases "
              f"({len(aliases)} canonical names).")

    for slug, label, _fetch_fn, open_ws_fn, _csv_name, parse_fn, periods in selected:
        if slug not in csvs:
            continue   # pull failed/skipped above — already flagged
        parsed = parse_fn(csvs[slug])
        parsed = _apply_aliases(parsed, aliases)
        _run_fill_phase(label, open_ws_fn, parsed, periods, today, args)

    # No Slack post — sheet-only (matches existing Captainship pattern).

    if failed:
        # NEVER say "done" when data is missing (Megan 2026-06-08: a report
        # must not read as completed on the Hub if it's missing data). Avoid
        # the word "done" entirely on this path so the Hub's success markers
        # don't trip; this run is INCOMPLETE.
        print(f"\n=== run INCOMPLETE — NOT marking complete. "
              f"{len(selected) - len(failed)}/{len(selected)} captainship(s) "
              f"filled; MISSING {len(failed)}: {failed} ===")
        print("  A skipped captainship is usually a flaky/slow Tableau load "
              "(often clears on a re-run) or a corrupted custom view (re-create "
              "it in Tableau if it keeps failing). The healthy tabs ARE filled.")
        return 1   # non-zero so the Hub flags it as incomplete
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
