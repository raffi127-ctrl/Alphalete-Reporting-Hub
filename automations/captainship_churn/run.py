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
                    today: dt.date, args) -> dict:
    """Fill one Captainship Churn tab. Returns {period: [went_dark_rep, ...]} —
    reps on the tab + recently active but absent from today's pull (empty = clean)."""
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

    # Detect reps that WENT DARK — read the tab BEFORE inserting today's column
    # (recent-history cols + rep_rows indices still valid). A rep on the roster +
    # recently active but missing from today's pull was dropped from the Tableau
    # view's filter or renamed past the alias (the Eveliz-Roca case) — flag it so
    # the run reads INCOMPLETE, not a silent green DONE. [[feedback_flag_unfilled_cells]]
    went_dark: dict = {}
    try:
        went_dark = fill.detect_went_dark(ws.get_all_values(), sections, parsed)
        if went_dark:
            for p, names in went_dark.items():
                print(f"  ⚠ {p}-day WENT DARK (on tab + recent data, absent from "
                      f"today's pull): {', '.join(names)}")
    except Exception as e:  # noqa: BLE001 — detection must never break the fill
        print(f"  (went-dark detection skipped: {type(e).__name__}: {str(e)[:80]})")

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
    return went_dark


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
                # RESILIENCE (Megan 2026-06-08): one pull failing must NOT crash
                # the run. The pull self-heals a transient flake via the shared
                # retry in download_crosstab_patchright; a genuinely corrupted
                # view still fails → skip + flag here, the rest continue.
                try:
                    csvs[slug] = fetch_fn(verbose=False, page=page)
                    print(f"    ✓ {csvs[slug]}")
                except Exception as e:
                    print(f"    ⚠ {label}: pull FAILED — skipping (the rest "
                          f"continue). {str(e).splitlines()[0][:160]}")
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
    all_reps: set = set()
    went_dark_all: dict = {}      # {tab label: {period: [rep names]}}
    for slug, label, _fetch_fn, open_ws_fn, _csv_name in selected:
        if slug not in csvs:
            continue   # pull failed/skipped above — already flagged
        parsed = pull.parse(csvs[slug])
        parsed = _apply_aliases(parsed, aliases)
        _wd = _run_fill_phase(label, open_ws_fn, parsed, today, args)
        if _wd:
            went_dark_all[label] = _wd
        all_reps.update(parsed.get("reps", {}).keys())

    # No Slack post — Captainship is sheet-only (Megan 2026-05-29).

    # Cross-reference filled reps against the 'Terminated ICDs' tab + ALERT the
    # runner about anyone terminated still on a tab (advisory — prints to the run
    # output + log, never removes a row). Folded into the manifest note below.
    _term_note = None
    if not args.dry_run and not args.only:
        try:
            from automations.shared import terminated_icds as _ti
            _hits, _flag = _ti.alert_terminated(
                sorted(all_reps), report_label="the Captainship Churn tabs")
            if _hits:
                _term_note = ("terminated ICD(s) still on the report (remove them): "
                              + ", ".join(h["report_name"] for h in _hits))
        except Exception:  # noqa: BLE001 — advisory must never fail the run
            pass

    # A rep that WENT DARK (dropped off a SUCCESSFUL pull) makes the run
    # INCOMPLETE even though every captainship pulled — the Eveliz-Roca case
    # (removed from the view's filter / renamed past the alias). Without this the
    # run read a silent green DONE while her row quietly stopped filling.
    _dark_note = None
    if went_dark_all:
        _bits = []
        for _lbl, _per in went_dark_all.items():
            _names = sorted({n for _ns in _per.values() for n in _ns})
            _bits.append(f"{_lbl} — {', '.join(_names)}")
        _dark_note = ("rep(s) on the tab stopped filling (recently active but "
                      "absent from today's pull): " + "; ".join(_bits))

    # Standard failure manifest → Hub "Retry failed only" + failure-help callout.
    # Only on a FULL run (an --only run is itself the retry). --only is a single
    # choice, so retry just the one when exactly one failed, else full re-run.
    if not args.dry_run and not args.only:
        try:
            from automations.shared import run_manifest as _rm
            if failed:
                _slug_by_label = {label: slug for slug, label, *_ in selected}
                _fslugs = [_slug_by_label[l] for l in failed if l in _slug_by_label]
                _rm.write_manifest(
                    "captainship-new-internet-wireless-churn",
                    failed=list(failed),
                    retry_args=(["--only", _fslugs[0]] if len(_fslugs) == 1 else []),
                    kind="report",
                    note=f"{len(failed)} churn report(s) failed: {failed}."
                         + (f" ⚠ {_dark_note}" if _dark_note else "")
                         + (f" ⚠ {_term_note}" if _term_note else ""),
                    remediation=_rm.make_remediation(
                        reason=f"{len(failed)} churn report(s) failed in "
                               f"Tableau: {', '.join(failed)}.",
                        fix="Usually a flaky/slow Tableau load (a re-run often "
                            "clears it) or a corrupted custom view (re-create it "
                            "in Tableau if it keeps failing). The healthy tab(s) "
                            "already filled.",
                        link="https://us-east-1.online.tableau.com/#/site/sci/"
                             "views/ATTTRACKER2_1-D2D/CHURN",
                        message=f"The Captainship Churn report couldn't pull "
                                f"these from Tableau today: {', '.join(failed)}. "
                                f"Can someone check those churn views are "
                                f"loading? A re-run often clears a flaky load."))
            elif _dark_note:
                # Pull succeeded for every captainship, but a rep silently went
                # dark → INCOMPLETE, not clean. Retry won't fix a filter/rename,
                # so the remediation points at the Tableau view + alias.
                _rm.write_manifest(
                    "captainship-new-internet-wireless-churn",
                    failed=list(went_dark_all.keys()), retry_args=[], kind="report",
                    note="⚠ " + _dark_note
                         + (f" ⚠ {_term_note}" if _term_note else ""),
                    remediation=_rm.make_remediation(
                        reason="A rep on a churn tab stopped filling while every "
                               "captainship pulled fine: " + _dark_note,
                        fix="This is almost always a Tableau-side change, not a "
                            "flaky pull: the rep was removed from that view's "
                            "filter, or renamed so the pull no longer matches her "
                            "sheet row. Re-add her to the captain's view filter "
                            "(and, if renamed, add the alias via "
                            "focus_office_att.aliases.save_alias), then re-run.",
                        link="https://us-east-1.online.tableau.com/#/site/sci/"
                             "views/ATTTRACKER2_1-D2D/CHURN",
                        message="Heads up — the Captainship Churn report filled "
                                "every captainship, but a rep stopped showing up: "
                                + _dark_note + ". Usually she was dropped from her "
                                "captain's Tableau view filter or renamed. Can "
                                "someone check the view?"))
            elif _term_note:
                _rm.write_manifest("captainship-new-internet-wireless-churn",
                                   failed=[], kind="report", note="⚠ " + _term_note)
            else:
                _rm.mark_clean("captainship-new-internet-wireless-churn",
                               kind="report")
        except Exception:
            pass

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
    if went_dark_all and not args.only:
        # Every pull succeeded but a rep silently went dark — do NOT read as a
        # clean DONE (this should be caught, not green). [[feedback_flag_unfilled_cells]]
        print(f"\n=== run INCOMPLETE — a rep stopped filling despite clean pulls. "
              f"{_dark_note} ===")
        print("  Check that rep's Tableau view filter (she was likely removed) "
              "or add an alias if she was renamed, then re-run.")
        return 1
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
