"""Captainship ABP & 6 days out — daily fill of the fiber captains'
'ABP & 6 days out - <captain> (ATT Fiber)' tabs in the "Captainship Metrics
Report - ABP and 6 days out" workbook.

One Tableau crosstab (ATTTRACKER2_1-D2D/Metrics, sheet "Metrics Call Last week
data (Internet)") feeds every captain: it is already grouped by `Captain's
Bonus Teams`, so we download once and slice per captainship in Python. Two
boxes per tab, each fed by its own column of that crosstab:

  ABP %                        <- 'New Internet ABP Mix % (Metrics)'
  % of Ongoing 6+ Days Sales   <- '% of sales scheduled 6+ days out (4 wks)'

That second column is the % Tableau shows in the TOOLTIP of the visible
6+-days-out count column. Tooltip measures ride along in the crosstab export,
so it comes down with everything else — see pull.py.

The Captainship Avg is Tableau's own per-team `Total` row, never a mean of the
owner cells.

Sheet-only, no Slack post (matches the sibling captainship reports).

  python -m automations.captainship_abp_6days.run
  python -m automations.captainship_abp_6days.run --dry-run
  python -m automations.captainship_abp_6days.run --only wayne
  python -m automations.captainship_abp_6days.run --only wayne,starr
  python -m automations.captainship_abp_6days.run --skip-download
  python -m automations.captainship_abp_6days.run --force-insert
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.shared.tableau_patchright import tableau_session
from automations.captainship_abp_6days import pull, fill
from automations.captainship_activation_rate.run import _apply_aliases
from automations.focus_office_att.aliases import load_aliases

REPORT_ID = "captainship-abp-6days"

# (slug, label) — one per tab in fill.TABS.
REPORTS = [
    ("wayne", "Wayne (ATT Fiber)"),
    ("starr", "Starr (ATT Fiber)"),
    ("chan",  "Chan (ATT Fiber)"),
    ("tony",  "Tony (ATT Fiber)"),
    ("sahil", "Sahil (ATT Fiber)"),
    # ABP only — see fill.TABS. Runs in the same pass off the same download, so
    # Rafael costs no extra Tableau session.
    ("rafael", "Rafael (Raf's Team)"),
]

CSV_NAME = "captainship_abp_6days_metrics.csv"

# Pretty names for the log, so '6days' doesn't read like a typo.
BOX_TITLE = {"abp": "ABP %", "6days": "6+ days out %"}


def _run_fill_phase(label: str, slug: str, parsed: dict, today: dt.date,
                    args) -> list:
    """Fill one captain's tab. Returns the list of owners Tableau reported that
    have no row on the tab and couldn't be added (empty = clean)."""
    print(f"\n--- {label}: parse + fill ---")
    office = parsed["office_total"]
    print(f"  ICD owners with data: {len(parsed['reps'])}")
    for box in pull.BOXES:
        print(f"    Captainship Avg {BOX_TITLE[box]:>14}: "
              f"{office.get(box, {}).get('pct', '-'):>8}")

    ws = fill.open_ws(slug)
    boxes = fill.find_boxes(ws)
    if len(boxes) != len(pull.BOXES):
        raise ValueError(
            f"expected {len(pull.BOXES)} boxes on {ws.title!r}, found "
            f"{sorted(boxes)}. The box headers are matched on 'ABP' / '6+ DAY' "
            f"in column A."
        )
    for b, sect in boxes.items():
        print(f"    {BOX_TITLE[b]:>14}: header row {sect['header_row']}, "
              f"{len(sect['rep_rows'])} existing ICDs")

    # Idempotency: if today's column is already open, refresh its values in
    # place instead of opening a second one.
    already = fill.today_already_filled(ws, boxes, today)
    skip_insert = already and not args.force_insert
    if skip_insert:
        print(f"  ⚠ '{fill._date_label(today)}' already in column B — "
              f"refreshing today's values in place (no new column).")

    # Runs every time, including a same-day refresh: an owner who appears in
    # Tableau after the day's first run still gets her row.
    added = fill.insert_missing_reps(ws, boxes, parsed,
                                     dry_run=args.dry_run, logfn=print)
    if added:
        for b, names in added.items():
            print(f"  + {BOX_TITLE.get(b, b)}: added {len(names)} new ICD(s): "
                  f"{names}")
    else:
        print("  (no new ICDs to add)")

    if not skip_insert:
        fill.ensure_headroom(ws, dry_run=args.dry_run, logfn=print)
        fill.insert_one_col_at_b(ws, boxes, dry_run=args.dry_run, logfn=print)

    print(f"  Write today ({fill._date_label(today)})...")
    summary = fill.write_today(ws, boxes, today, parsed,
                               dry_run=args.dry_run, logfn=print)
    unmatched: list = []
    for b, s in summary.items():
        extra = f", {len(s['unmatched'])} unmatched" if s["unmatched"] else ""
        print(f"    {BOX_TITLE[b]:>14}: {s['filled']} filled, "
              f"{s['cleared']} blanked{extra}")
        unmatched.extend(s["unmatched"])
    return sorted(set(unmatched))


def _parse_only(arg):
    if not arg:
        return None
    return {s.strip().lower() for s in arg.split(",") if s.strip()} or None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_abp_6days")
    ap.add_argument("--date", default=None,
                    help="Override today's date (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen, but don't write.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the cached Tableau CSV in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Open a NEW column even if today's date is already "
                         "in column B.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated captains to run: "
                         + ", ".join(s for s, _ in REPORTS)
                         + ". Defaults to all.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    only = _parse_only(args.only)
    selected = [r for r in REPORTS if only is None or r[0] in only]
    if not selected:
        print(f"No captains match --only={args.only}. "
              f"Valid: {[r[0] for r in REPORTS]}")
        return 1

    print(f"=== Captainship ABP & 6 days out — {today.isoformat()} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    print(f"Captains: {[r[1] for r in selected]}")

    # --- Phase 1: ONE crosstab for every captain ---
    csv_path = Path(tempfile.gettempdir()) / CSV_NAME
    if args.skip_download:
        if not csv_path.exists():
            print(f"  ⚠ --skip-download set but no cached CSV at {csv_path}")
            return 1
        print(f"  ✓ cached {csv_path}")
    else:
        print("\nPhase 1: one Tableau session, one Metrics crosstab...")
        try:
            with tableau_session(verbose=False) as page:
                csv_path = pull.fetch(verbose=False, page=page)
            print(f"  ✓ {csv_path}")
        except Exception as e:
            # The pull feeds EVERY tab, so a failure here is total — there is
            # no partial success to preserve. Fail loudly, don't half-fill.
            msg = str(e).splitlines()[0][:200]
            print(f"  ⚠ Metrics crosstab pull FAILED: {msg}")
            _manifest(failed=["Metrics crosstab"], dry_run=args.dry_run,
                      only=args.only,
                      note=f"the Metrics crosstab pull failed: {msg}")
            print("\n=== run INCOMPLETE — no tab was filled. ===")
            return 1

    # --- Phase 2: slice + fill each captain ---
    print("\nPhase 2: fill destination tabs")
    aliases = load_aliases()
    if aliases:
        print(f"  Loaded {sum(len(v) for v in aliases.values())} aliases "
              f"({len(aliases)} canonical names).")

    failed: list = []
    unmatched_all: dict = {}
    for slug, label in selected:
        try:
            parsed = pull.parse(csv_path, pull.CAPTAIN_TEAM[slug])
            parsed = _apply_aliases(parsed, aliases)
            _un = _run_fill_phase(label, slug, parsed, today, args)
            if _un:
                unmatched_all[label] = _un
                print(f"  ⚠ {label}: in Tableau but NOT on the tab: "
                      f"{', '.join(_un)}")
        except Exception as e:  # noqa: BLE001 — one captain must not kill the rest
            msg = str(e).splitlines()[0][:200]
            print(f"  ⚠ {label}: FAILED — skipping (the rest continue). {msg}")
            failed.append(label)

    _note = None
    if unmatched_all:
        _note = ("owner(s) in Tableau with no row on the tab: "
                 + "; ".join(f"{k} — {', '.join(v)}"
                             for k, v in unmatched_all.items()))
        print(f"\n⚠ {_note}")
    _manifest(failed=failed, dry_run=args.dry_run, only=args.only, note=_note)

    if failed:
        # NEVER read 'done' when data is missing.
        print(f"\n=== run INCOMPLETE — {len(selected) - len(failed)}/"
              f"{len(selected)} filled; MISSING {failed} ===")
        return 1
    print("\n=== done ===")
    return 0


def _manifest(*, failed, dry_run, only, note=None) -> None:
    """Standard failure manifest -> Hub 'Retry failed only' + failure callout."""
    if dry_run or only:
        return
    try:
        from automations.shared import run_manifest as _rm
        if failed:
            _rm.write_manifest(
                REPORT_ID, failed=list(failed), retry_args=[], kind="report",
                note=(note or f"{len(failed)} ABP / 6-days-out fill(s) failed."),
                remediation=_rm.make_remediation(
                    reason=f"ABP & 6 days out failed for: {', '.join(failed)}.",
                    fix="Usually a flaky/slow Tableau load (a re-run often "
                        "clears it). If the log says a column is missing, the "
                        "Metrics view was renamed — the 6-days-out % is a "
                        "TOOLTIP measure, so dropping it from the tooltip "
                        "removes it from the export too. If it says no rows "
                        "for a team, the SFDC team was renamed; update "
                        "captainship_activation_rate.pull.CAPTAIN_TEAM.",
                    link="https://us-east-1.online.tableau.com/#/site/sci/"
                         "views/ATTTRACKER2_1-D2D/Metrics",
                    message="The Captainship ABP & 6 days out report couldn't "
                            f"fill: {', '.join(failed)}. Can someone check the "
                            "Metrics view is loading? A re-run often clears a "
                            "flaky load."))
        elif note:
            _rm.write_manifest(REPORT_ID, failed=[], kind="report",
                               note="⚠ " + note)
        else:
            _rm.mark_clean(REPORT_ID, kind="report")
    except Exception:  # noqa: BLE001 — manifest must never fail the run
        pass


if __name__ == "__main__":
    sys.exit(main())
