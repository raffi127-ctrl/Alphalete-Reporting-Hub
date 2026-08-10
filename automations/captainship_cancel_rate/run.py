"""Captainship Cancel Rate — daily fill of the 5 ATT Fiber captains' tabs.

WHAT IT FILLS
  Workbook: "Captainship Metrics Report - Cancel Rate"
  Tabs:     Cancel Rate - Wayne / Starr / Chan / Tony / Sahil (ATT Fiber)
  Sections: CANCEL RATE 0-30 DAYS  and  CANCEL RATE 30-60 DAYS
  Rows:     Captainship Avg + one row per ICD owner
  Column:   today's — inserted at B, history shifts right

WHERE THE NUMBERS COME FROM (full path — see pull.py for the detail)
  Tableau -> ATT TRACKER 2_1 - D2D -> view "Metrics"
          -> worksheet "Metrics Call Last week data (Internet)"
          -> rows grouped by "Captain's Bonus Teams", read at ICD-owner level
             (the export's 'Rep Name' column is optional — see pull.py)
  0-30  : column "0-30 day New Internet cancel rate"           (verbatim)
  30-60 : column "30-60 day New Internet activation rate", INVERTED
          (100% - activation), because the workbook has no 30-60 cancel column.

Writes to the LIVE workbook by default. --sandbox retargets the whole run at
a duplicate of it for practice; --dry-run writes nothing at all.

  python -m automations.captainship_cancel_rate.run                # live
  python -m automations.captainship_cancel_rate.run --sandbox      # practice
  python -m automations.captainship_cancel_rate.run --dry-run
  python -m automations.captainship_cancel_rate.run --only wayne
  python -m automations.captainship_cancel_rate.run --skip-download
  python -m automations.captainship_cancel_rate.run --force-insert
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.shared.tableau_patchright import tableau_session
from automations.captainship_cancel_rate import captains as C, fill, pull

REPORT_ID = "captainship-cancel-rate"
CSV_NAME = "captainship_cancel_rate.csv"
# Texas company — the report date is always Central, never the box's clock.
TZ = ZoneInfo("America/Chicago")


def _today(arg: str | None) -> dt.date:
    if arg:
        return dt.date.fromisoformat(arg)
    return dt.datetime.now(TZ).date()


def _fill_one(cap, parsed: dict, today: dt.date, args) -> dict:
    """Fill one captain's tab. Returns a per-captain result dict."""
    label = f"{cap.team} -> {cap.tab}"
    print(f"\n--- {label} ---")
    data = pull.for_team(parsed, cap.team)
    if not data.get("reps") and not data.get("avg"):
        raise RuntimeError(
            f"No rows for Captain's Bonus Teams == {cap.team!r} in the Metrics "
            f"crosstab (teams present: {', '.join(parsed.get('teams_seen', []))}). "
            f"The team was renamed or dropped from the view's filter.")

    print(f"  Tableau: {len(data['reps'])} ICD owner(s); "
          f"avg 0-30 {data['avg'].get(pull.P_030, '-')}, "
          f"30-60 {data['avg'].get(pull.P_3060, '-')}")

    ws = fill.open_ws(cap.tab, sandbox=args.sandbox)
    sections = fill.find_sections(ws)
    if len(sections) != len(fill.SECTION_LABELS):
        raise RuntimeError(
            f"Expected {len(fill.SECTION_LABELS)} sections on '{cap.tab}', found "
            f"{sorted(sections)}. The col-A section labels changed.")
    for period, sect in sections.items():
        print(f"    {period:>5}: header row {sect['header_row']}, "
              f"{len(sect['rep_rows'])} ICD row(s)")

    fill.ensure_columns(ws, dry_run=args.dry_run, logfn=print)

    already = fill.today_already_filled(ws, sections, today)
    if already and not args.force_insert:
        print(f"  '{fill._date_label(today)}' already in B — skipping the column "
              f"insert (idempotent). Values still refresh from today's pull.")
    else:
        fill.insert_col_at_b(ws, sections, dry_run=args.dry_run, logfn=print)

    added = fill.insert_missing_reps(ws, sections, data,
                                     dry_run=args.dry_run, logfn=print)
    for period, names in added.items():
        print(f"  + {period}: added {len(names)} ICD row(s): {names}")
    if not added:
        print("  (no new ICD rows to add)")

    # A rep who is new to this captainship gets ONE heads-up in
    # #revision-emails, from whichever report sees them first — the log tab
    # keeps the other four quiet. Advisory: the rows are already in.
    # [[project_new_owners]]
    try:
        from automations.new_owners import captain_watch as _cw
        _cw.observe_added(added, captain=cap.slug,
                          source="Captainship Cancel Rate",
                          dry_run=args.dry_run)
    except Exception as _e:  # noqa: BLE001 — never break the fill on a notice
        print(f"  (new-rep notice skipped: {type(_e).__name__}: {str(_e)[:60]})")

    print(f"  Write {fill._date_label(today)}...")
    summary = fill.write_today(ws, sections, today, data,
                               dry_run=args.dry_run, logfn=print)

    # An owner who has recent history but no value today STOPPED filling —
    # a dropped view filter or a rename past the alias. Never a silent pass.
    history = ({} if args.dry_run
               else fill.recent_history(ws, sections))
    went_dark: dict = {}
    expected_blank: dict = {}
    for period, s in summary.items():
        dark = [n for n in s["blank"]
                if history.get(period, {}).get(fill._norm(n))]
        # A known wind-down going blank is EXPECTED, not a dropped filter —
        # note it, but never fail the report on it (see C.INACTIVE_ICDS).
        winding = [n for n in dark if C.is_inactive(n)]
        dark = [n for n in dark if not C.is_inactive(n)]
        if winding:
            expected_blank[period] = sorted(winding)
        if dark:
            went_dark[period] = sorted(dark)
        extra = ""
        if s["unmatched"]:
            extra += f", {len(s['unmatched'])} not on the tab: {s['unmatched']}"
        if s["blank"]:
            extra += f", {len(s['blank'])} blank"
        print(f"    {period:>5}: avg {s['avg'] or '-'}, {s['filled']} filled{extra}")
    for period, names in expected_blank.items():
        print(f"  · {period}: blank as expected (winding down, row kept for the "
              f"history): {', '.join(names)}")
    for period, names in went_dark.items():
        print(f"  ⚠ {period}: STOPPED filling (had recent data, nothing today): "
              f"{', '.join(names)}")

    return {"summary": summary, "added": added, "went_dark": went_dark}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_cancel_rate")
    ap.add_argument("--date", default=None, help="Override today (YYYY-MM-DD).")
    ap.add_argument("--sandbox", action="store_true",
                    help="Practice run: write to the SANDBOX duplicate instead "
                         "of the live workbook.")
    # Accepted and ignored — the live workbook is now the default, but saved
    # rerun commands and older scheduler configs still pass --real.
    ap.add_argument("--real", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen; write nothing.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the cached Metrics crosstab in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Insert a new column even if today's label is in B.")
    ap.add_argument("--only", choices=C.SLUGS, default=None,
                    help="Run one captain only.")
    args = ap.parse_args(argv)

    today = _today(args.date)
    selected = [c for c in C.CAPTAINS if args.only is None or c.slug == args.only]
    target = C.sheet_id(args.sandbox)

    mode = "DRY-RUN" if args.dry_run else ("SANDBOX" if args.sandbox else "LIVE")
    print(f"=== Captainship Cancel Rate — {today.isoformat()} ({mode}) ===")
    print(f"Workbook: https://docs.google.com/spreadsheets/d/{target}/edit")
    print(f"Captains: {[c.slug for c in selected]}")

    # --- Phase 1: one Tableau session, one crosstab, all 5 captains ---
    csv_path = Path(tempfile.gettempdir()) / CSV_NAME
    if args.skip_download:
        if not csv_path.exists():
            print(f"  ⚠ --skip-download set but no cached CSV at {csv_path}")
            return 1
        print(f"\nPhase 1: cached crosstab {csv_path}")
    else:
        print("\nPhase 1: Tableau — Metrics crosstab "
              f"('{pull.METRICS_SHEET}')...")
        with tableau_session(verbose=False) as page:
            csv_path = pull.fetch(csv_path, page=page, verbose=False)
        print(f"  ✓ {csv_path}")

    parsed = pull.parse(csv_path)
    shape = parsed.get("shape", "?")
    print(f"  Crosstab shape: {shape} "
          f"('Rep Name' is optional — both shapes give owner-level rows)")
    print(f"  Teams in the crosstab: {', '.join(parsed['teams_seen'])}")

    # Both shapes parse, but they are NOT equally correct. Only the collapsed
    # (owner-level) export gives an honest 30-60 rate — expanding restricts the
    # rows to reps with current-week data while 30-60 is a 30-60-days-ago
    # cohort, so reps who sold then and not now fall out of the owner subtotal
    # (pull.py's docstring has the measured drift). 0-30 is unaffected. That
    # would fill silently-wrong numbers with no crash, so say so LOUDLY.
    shape_warning = None
    if shape == "rep-expanded":
        shape_warning = (
            "The Metrics crosstab came back REP-EXPANDED. 0-30 is fine, but "
            "the 30-60 rates are computed over a partial cohort and read a few "
            "tenths (up to several points on low-volume ICDs) off the truth. "
            "This report wants the COLLAPSED owner-level export — check that "
            "pull.METRICS_URL still points at the plain view with no saved "
            "rep-expanded custom view attached.")
        print(f"\n  ⚠ {shape_warning}\n")

    # --- Phase 2: fill each captain's tab ---
    print("\nPhase 2: fill the captain tabs")
    failed: list = []
    went_dark_all: dict = {}
    unmatched_all: dict = {}
    for cap in selected:
        try:
            res = _fill_one(cap, parsed, today, args)
        except Exception as e:  # noqa: BLE001 — one bad tab must not kill the rest
            print(f"  ⚠ {cap.tab}: FAILED — {type(e).__name__}: "
                  f"{str(e).splitlines()[0][:200]}")
            failed.append(cap.slug)
            continue
        if res["went_dark"]:
            went_dark_all[cap.tab] = res["went_dark"]
        um = sorted({n for s in res["summary"].values() for n in s["unmatched"]})
        if um:
            unmatched_all[cap.tab] = um

    for tab, names in unmatched_all.items():
        print(f"\n  ℹ {tab}: Tableau has ICD(s) with no row on the tab — a row "
              f"was appended for each: {', '.join(names)}")

    # --- Manifest (Hub 'Retry failed only' + failure-help callout) ---
    if not args.dry_run and args.only is None:
        _write_manifest(failed, went_dark_all, args, shape_warning)

    if failed:
        print(f"\n=== run INCOMPLETE — NOT marking complete. "
              f"{len(selected) - len(failed)}/{len(selected)} tabs filled; "
              f"MISSING: {failed} ===")
        return 1
    if went_dark_all:
        print("\n=== run INCOMPLETE — every tab filled, but an ICD stopped "
              "filling. Check that owner's Tableau view filter / alias. ===")
        return 1
    print("\n=== done ===")
    return 0


def _write_manifest(failed: list, went_dark_all: dict, args,
                    shape_warning: str | None = None) -> None:
    try:
        from automations.shared import run_manifest as _rm
    except Exception:
        return
    dark_note = None
    if went_dark_all:
        bits = [f"{tab} — " + ", ".join(sorted({n for ns in per.values() for n in ns}))
                for tab, per in went_dark_all.items()]
        dark_note = ("ICD(s) stopped filling (recent history, nothing today): "
                     + "; ".join(bits))
    try:
        if failed:
            _rm.write_manifest(
                REPORT_ID, failed=list(failed),
                retry_args=(["--only", failed[0]] if len(failed) == 1 else [])
                           + (["--sandbox"] if args.sandbox else []),
                kind="report",
                note=f"{len(failed)} captain tab(s) failed: {failed}."
                     + (f" ⚠ {dark_note}" if dark_note else ""),
                remediation=_rm.make_remediation(
                    reason=f"The Cancel Rate fill failed for: {', '.join(failed)}.",
                    fix="Usually a flaky Tableau load (a re-run often clears it) "
                        "or a renamed team / column in the Metrics view. If the "
                        "log says a column is missing, the view changed — update "
                        "automations/captainship_cancel_rate/pull.py.",
                    link=pull.METRICS_URL,
                    message="The Captainship Cancel Rate report couldn't fill "
                            f"these captain tabs today: {', '.join(failed)}. "
                            "Can someone check the Metrics view is loading?"))
        elif dark_note:
            _rm.write_manifest(
                REPORT_ID, failed=list(went_dark_all.keys()),
                retry_args=(["--sandbox"] if args.sandbox else []), kind="report",
                note="⚠ " + dark_note,
                remediation=_rm.make_remediation(
                    reason="Every captain tab filled, but an ICD that had recent "
                           "data stopped: " + dark_note,
                    fix="Almost always a Tableau-side change, not a flaky pull: "
                        "the ICD was dropped from the Captain's Bonus Teams "
                        "filter, or renamed so the pull no longer matches the "
                        "sheet row. Re-add them to the view, or add the alias "
                        "via focus_office_att.aliases.save_alias, then re-run.",
                    link=pull.METRICS_URL,
                    message="Heads up — the Cancel Rate report filled every "
                            "captain tab, but an ICD stopped showing up: "
                            + dark_note))
        elif shape_warning:
            # Tabs all filled, so this is not a failure — but the 30-60 numbers
            # are off and a re-run can't fix it (the view's shape is the
            # problem, not a flaky load). Flag it; don't mark clean.
            _rm.write_manifest(
                REPORT_ID, failed=[], retry_args=[], kind="report",
                note="⚠ 30-60 rates may be slightly off — " + shape_warning,
                remediation=_rm.make_remediation(
                    reason="Every captain tab filled, but the Metrics crosstab "
                           "came back rep-expanded: " + shape_warning,
                    fix="Re-running will NOT fix this — the Tableau view's row "
                        "depth is the problem. Open the Metrics view, make sure "
                        "no rep-expanded custom view is applied (the rep '+' "
                        "above the ICD name is collapsed), then re-run. 0-30 is "
                        "unaffected either way.",
                    link=pull.METRICS_URL,
                    message="Heads up — the Cancel Rate report filled every "
                            "captain tab, but the Tableau view came back "
                            "rep-expanded, so today's 30-60 numbers are a bit "
                            "off. 0-30 is fine. Can someone check the view?"))
        else:
            _rm.mark_clean(REPORT_ID, kind="report")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
