"""Combined runner for the Owners Metrics Report churn tabs.

Phase 1 (Fiber): pulls Wayne / Starr Rodenhurst / Chan Park /
Tony Chavez / Sahil Multani — one Tableau patchright session, five
Crosstab downloads, five sheet fills. Sheet-only (no Slack post).
All five tabs share the same column / section layout (CHURN TIERS at
rows 1-3, captain name at row 7, sections from row 8 with
0-30 / 30 / 60 / 90 buckets).

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

from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)
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
    ("chan", "Chan Park (ATT Fiber)",
     pull.fetch_fiber_chan, fill.open_ws_fiber_chan,
     "owners_fiber_chan.csv", pull.parse, pull.PERIODS),
    ("tony", "Tony Chavez (ATT Fiber)",
     pull.fetch_fiber_tony, fill.open_ws_fiber_tony,
     "owners_fiber_tony.csv", pull.parse, pull.PERIODS),
    ("sahil", "Sahil Multani (ATT Fiber)",
     pull.fetch_fiber_sahil, fill.open_ws_fiber_sahil,
     "owners_fiber_sahil.csv", pull.parse, pull.PERIODS),
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


# Parsed all-teams churn view per program, pulled at most ONCE per run (reset each
# process). Reps who moved captainships are backfilled from here so their old
# captain's tab keeps filling instead of silently going dark.
_ALLTEAMS_PARSE_CACHE: dict = {}
# The all-teams backfill crosstab is as flake-prone as any Tableau download; retry
# it so a transient flake doesn't falsely flag a moved rep as gone.
BACKFILL_PULL_TRIES = 3


def _program_of(parse_fn) -> str:
    """Map a REPORTS parse_fn to its program key for the all-teams source lookup."""
    if parse_fn is pull.parse_b2b:
        return "b2b"
    if parse_fn is pull.parse_nds:
        return "nds"
    return "fiber"


def _backfill_moved_owners(program: str, dark_names: list, aliases: dict) -> dict:
    """Return {display_name: periods} for went-dark owners found in the program's
    all-teams churn view — reps who moved SFDC captainships but are still on their
    old captain's sheet tab. Pulls the all-teams view at most once per run (cached).
    Empty when the program has no all-teams source wired or the owner is absent
    everywhere (genuinely gone → stays flagged)."""
    src = pull.ALLTEAMS_CHURN_SOURCE.get(program)
    if not src or not dark_names:
        return {}
    url, worksheet, parse_fn = src
    if program not in _ALLTEAMS_PARSE_CACHE:
        out = Path(tempfile.gettempdir()) / f"owners_{program}_allteams.csv"
        # RETRY the backfill pull: this all-teams crosstab is a second Tableau
        # download and just as flake-prone as the rest (needs 2-3 tries). A single
        # flake here used to silently drop a MOVED rep — she'd stay went-dark and
        # the run flagged INCOMPLETE even though her data was right there in the
        # all-teams view (Max Powell, moved Luis→Alex's team, 2026-07-09). Retry so
        # a transient flake no longer falsely flags a moved rep.
        parsed_all = {"reps": {}}
        for _try in range(1, BACKFILL_PULL_TRIES + 1):
            try:
                print(f"  ↻ pulling {program} all-teams churn (try {_try}/"
                      f"{BACKFILL_PULL_TRIES}) to backfill moved rep(s): "
                      f"{', '.join(dark_names)}")
                download_crosstab_patchright(url, worksheet, out, verbose=False)
                parsed_all = _apply_aliases(parse_fn(out), aliases)
                if parsed_all.get("reps"):
                    break   # got names — good pull, stop retrying
            except Exception as e:  # noqa: BLE001 — backfill is best-effort
                print(f"  (all-teams backfill pull try {_try} failed: "
                      f"{type(e).__name__}: {str(e).splitlines()[0][:80]})")
        _ALLTEAMS_PARSE_CACHE[program] = parsed_all
    allreps = _ALLTEAMS_PARSE_CACHE[program].get("reps", {})
    low = {k.lower(): k for k in allreps}
    got: dict = {}
    for nm in dark_names:
        k = low.get(nm.lower())
        # Only accept a real hit — a name present with an actual pct somewhere.
        if k and any(isinstance(v, dict) and v.get("pct")
                     for v in allreps[k].values()):
            got[nm] = allreps[k]
    return got


def _run_fill_phase(label: str, open_ws_fn, parsed: dict, periods: tuple,
                    today: dt.date, args, program: str = "fiber",
                    aliases: dict | None = None) -> dict:
    """Fill one tab. Returns {period: [went_dark_rep, ...]} — reps on the tab +
    recently active but absent from today's pull (empty dict = clean)."""
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

    # Detect reps that WENT DARK — read the tab BEFORE inserting today's column
    # (so the recent-history columns + rep_rows indices are still valid). A rep on
    # the roster + recently active, but missing from today's pull, means she was
    # dropped from the Tableau view's filter or renamed past the alias (the
    # Eveliz-Roca case). Surfaced so the run flags INCOMPLETE, not a silent DONE.
    went_dark: dict = {}
    try:
        went_dark = fill.detect_went_dark(ws.get_all_values(), sections, parsed)
        if went_dark:
            for p, names in went_dark.items():
                print(f"  ⚠ {p}-day WENT DARK (on tab + recent data, absent from "
                      f"today's pull): {', '.join(names)}")
    except Exception as e:  # noqa: BLE001 — detection must never break the fill
        print(f"  (went-dark detection skipped: {type(e).__name__}: {str(e)[:80]})")

    # A rep who WENT DARK because she moved captainships (still on THIS captain's
    # tab, but no longer returned by his SFDC-team pull) is backfilled from the
    # program's all-teams churn view so her row keeps filling — reps change teams
    # routinely (Megan 2026-07-09). Only reps genuinely absent everywhere (gone
    # from all teams) stay dark and get flagged as before.
    if went_dark:
        dark_names = sorted({n for names in went_dark.values() for n in names})
        backfilled = _backfill_moved_owners(program, dark_names, aliases or {})
        for nm, periods_data in backfilled.items():
            parsed["reps"][nm] = periods_data
            print(f"  ↳ backfilled {nm} from {program} all-teams churn "
                  f"(moved captainships — kept on this tab)")
        if backfilled:
            # Re-detect: backfilled reps are now present in `parsed`, so they clear.
            went_dark = fill.detect_went_dark(ws.get_all_values(), sections, parsed)

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
    return went_dark


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
                         "starr, chan, tony, sahil. B2B: carlos, eveliz. "
                         "NDS: khalil, colten, jairo. Defaults to all.")
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
                # Resilient: one captain's pull failing must NOT kill the rest.
                # The pull self-heals a transient flake via the shared retry in
                # download_crosstab_patchright; a genuinely corrupted view still
                # fails both attempts → skip + flag here (Eve glitch 2026-06-05).
                try:
                    csvs[slug] = fetch_fn(verbose=False, page=page)
                    print(f"    ✓ {csvs[slug]}")
                except Exception as e:
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

    all_reps: set = set()
    went_dark_all: dict = {}      # {tab label: {period: [rep names]}}
    for slug, label, _fetch_fn, open_ws_fn, _csv_name, parse_fn, periods in selected:
        if slug not in csvs:
            continue   # pull failed/skipped above — already flagged
        parsed = parse_fn(csvs[slug])
        _raw_names = sorted(parsed.get("reps", {}).keys())
        parsed = _apply_aliases(parsed, aliases)
        _aliased_names = sorted(parsed.get("reps", {}).keys())
        # DIAGNOSTIC (--only runs): dump the raw + aliased rep names the pull
        # returned to the 'Inspect Out' sheet, so a Tableau rename the alias
        # doesn't cover (a rep silently dropping off) is visible off-machine.
        if args.only:
            try:
                import gspread as _gs
                from automations.recruiting_report import fill as _dbg
                from automations.day_orchestrator.mini_control import CONTROL_SHEET_ID
                _sh = _dbg._client().open_by_key(CONTROL_SHEET_ID)
                try:
                    _ws = _sh.worksheet("Inspect Out")
                except _gs.WorksheetNotFound:
                    _ws = _sh.add_worksheet(title="Inspect Out", rows=50, cols=4)
                _ws.clear()
                _ws.update([["slug", "n", "raw_names (from Tableau)",
                             "aliased_names (after alias)"],
                            [slug, str(len(_raw_names)),
                             ", ".join(_raw_names), ", ".join(_aliased_names)]], "A1")
                print(f"  (diag: dumped {len(_raw_names)} raw rep name(s) to Inspect Out)")
            except Exception as _e:  # noqa: BLE001 — diag must never fail the run
                print(f"  (diag dump failed: {type(_e).__name__}: {str(_e)[:80]})")
        _wd = _run_fill_phase(label, open_ws_fn, parsed, periods, today, args,
                              program=_program_of(parse_fn), aliases=aliases)
        if _wd:
            went_dark_all[label] = _wd
        all_reps.update(parsed.get("reps", {}).keys())

    # No Slack post — sheet-only (matches existing Captainship pattern).

    # Cross-reference filled reps against the 'Terminated ICDs' tab + ALERT the
    # runner about anyone terminated still on a tab (advisory — prints to the run
    # output + log, never removes a row). Folded into the manifest note below.
    _term_note = None
    if not args.dry_run and not args.only:
        try:
            from automations.shared import terminated_icds as _ti
            _hits, _flag = _ti.alert_terminated(
                sorted(all_reps), report_label="the Owners Metrics Churn tabs")
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

    # Standard failure manifest → powers the Hub's "Retry failed only" button
    # (re-pull just the failed captainships via --only) + the failure-help
    # callout (why/fix/link/message). Only on a FULL run — an --only run is
    # itself the retry and shouldn't rewrite the full-run failure list.
    if not args.dry_run and not args.only:
        try:
            from automations.shared import run_manifest as _rm
            if failed:
                _slug_by_label = {label: slug for slug, label, *_ in selected}
                _fslugs = [_slug_by_label[l] for l in failed if l in _slug_by_label]
                _rm.write_manifest(
                    "owners-metrics-churn", failed=list(failed),
                    retry_args=(["--only", ",".join(_fslugs)] if _fslugs else []),
                    kind="captainship",
                    note=f"{len(failed)} captainship churn pull(s) failed."
                         + (f" ⚠ {_dark_note}" if _dark_note else "")
                         + (f" ⚠ {_term_note}" if _term_note else ""),
                    remediation=_rm.make_remediation(
                        reason=f"{len(failed)} captainship churn pull(s) failed "
                               f"in Tableau: {', '.join(failed)}.",
                        fix="Usually a flaky/slow Tableau load (a re-run often "
                            "clears it) or a corrupted custom view (re-create it "
                            "in Tableau if it keeps failing). The healthy tabs "
                            "already filled — use 'Retry failed only' to re-pull "
                            "just these.",
                        link="https://us-east-1.online.tableau.com/#/site/sci/"
                             "views/ATTTRACKER2_1-D2D/CHURN",
                        message=f"The Owners Metrics Churn report couldn't pull "
                                f"these captainships from Tableau today: "
                                f"{', '.join(failed)}. Can someone check those "
                                f"churn views are loading? A re-run often clears "
                                f"a flaky load."))
            elif _dark_note:
                # Pull succeeded for every captainship, but a rep silently went
                # dark → INCOMPLETE, not clean. Retry won't fix a filter/rename,
                # so the remediation points at the Tableau view + alias, not a
                # re-pull.
                _rm.write_manifest(
                    "owners-metrics-churn", failed=list(went_dark_all.keys()),
                    retry_args=[], kind="captainship",
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
                             "views/ATTTRACKER-B2B/CHURNRATES",
                        message="Heads up — the Owners Metrics Churn report filled "
                                "every captainship, but a rep stopped showing up: "
                                + _dark_note + ". Usually she was dropped from her "
                                "captain's Tableau view filter or renamed. Can "
                                "someone check the view?"))
            elif _term_note:
                _rm.write_manifest("owners-metrics-churn", failed=[],
                                   kind="captainship", note="⚠ " + _term_note)
            else:
                _rm.mark_clean("owners-metrics-churn", kind="captainship")
        except Exception:
            pass

    # EXIT-CODE CONTRACT (Megan 2026-07-23 — 3rd report of this class, after
    # tableau_screenshots 48d94af/19cce3c and vantura_board_audit 8fa4e2e).
    # The day-orchestrator reads ANY non-zero exit as a hard FAILED page and
    # fires the immediate failure email, short-circuiting the graceful
    # manifest -> reconcile -> INCOMPLETE path. So reserve non-zero for a
    # GENUINE crash: a scrape/auth/IO exception. A captainship whose Tableau
    # pull RAISED lands in `failed` (a real scrape exception, caught so the
    # healthy tabs still fill) -> that still exits 1. But a rep who WENT DARK on
    # otherwise-clean pulls is a data-quality FINDING (fill-but-flag), not a
    # crash — the fill completed, one rep is just absent from the view. That
    # exits 0 and surfaces as a SOFT INCOMPLETE through the run-manifest
    # (ok=False, already written above), which verify:manifest reads at the
    # checkpoint. The MANIFEST — not the exit code — is what keeps a
    # data-missing run from reading as a green DONE (Megan's 2026-06-08 rule).
    if failed:
        # A pull that RAISED = a genuine scrape/IO exception (caught so the rest
        # continue). NEVER say "done" when data is missing (Megan 2026-06-08: a
        # report must not read as completed on the Hub if it's missing data).
        # Avoid the word "done" entirely so the Hub's success markers don't trip.
        print(f"\n=== run INCOMPLETE — NOT marking complete. "
              f"{len(selected) - len(failed)}/{len(selected)} captainship(s) "
              f"filled; MISSING {len(failed)}: {failed} ===")
        print("  A skipped captainship is usually a flaky/slow Tableau load "
              "(often clears on a re-run) or a corrupted custom view (re-create "
              "it in Tableau if it keeps failing). The healthy tabs ARE filled.")
        return 1   # genuine scrape exception → hard FAILED page (a human needed)
    if went_dark_all and not args.only:
        # Every pull SUCCEEDED but a rep silently went dark — a data-quality
        # FINDING, not a crash (Megan 2026-07-05: this should be caught, not a
        # green DONE; 2026-07-23: but it should NOT hard-page as FAILED either —
        # the fill ran to completion). Exit 0; the ok=False manifest written
        # above already carries this as a SOFT INCOMPLETE note + remediation.
        print(f"\n=== run INCOMPLETE (finding) — a rep stopped filling despite "
              f"clean pulls. {_dark_note} ===")
        print("  Check that rep's Tableau view filter (she was likely removed) "
              "or add an alias if she was renamed, then re-run. (Recorded as a "
              "soft INCOMPLETE via the run-manifest — not a hard failure.)")
        return 0   # finding, not a crash → soft INCOMPLETE via manifest, no page
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
