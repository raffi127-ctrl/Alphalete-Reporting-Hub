"""Int WoW Report — Penetration % — weekly run.

Runs every Tuesday. Computes the weekending Sunday (Central Time), pulls the
Fiber Lead Performance penetration % per owner + the national total from
Tableau (or loads a manually-downloaded CSV for a backfill), then inserts a
new column at B of the 'Penetration %' table on the Int WoW Report tab.

  # weekly live run (pulls Tableau, writes the sandbox tab):
  python -m automations.int_wow_penetration.run

  # backfill a specific week from a manual CSV (no Tableau pull):
  python -m automations.int_wow_penetration.run --csv "<path>" --week-label "WE 5.24"

  python -m automations.int_wow_penetration.run --dry-run
  python -m automations.int_wow_penetration.run --date 2026-05-31   # override
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.int_wow_penetration import pull, fill, slack_post
from automations.focus_office_att.aliases import load_aliases

CENTRAL = ZoneInfo("America/Chicago")


# Standard run-manifest id — the orchestrator's verify reads
# output/manifests/int-wow-penetration.json (schedule_config verify.report_id
# must match). Seeded as failed at run start; mark_clean'd on a clean fill.
MANIFEST_ID = "int-wow-penetration"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="int_wow_penetration")
    ap.add_argument("--date", default=None,
                    help="Override the run date (YYYY-MM-DD). Weekending is "
                         "the Sunday on/before it. Default = today (Central).")
    ap.add_argument("--week-label", default=None,
                    help="Override the column header, e.g. 'WE 5.24'. Use for "
                         "a backfill whose data week differs from the run date.")
    ap.add_argument("--csv", default=None,
                    help="Parse this CSV instead of pulling Tableau (backfill).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen; don't write to the Sheet.")
    ap.add_argument("--force", action="store_true",
                    help="Insert a new column even if this week's label is "
                         "already at column B.")
    ap.add_argument("--no-slack", action="store_true",
                    help="Skip the Slack 'report updated' post (use for "
                         "historical backfills).")
    args = ap.parse_args(argv)

    # --- weekending label ---
    if args.week_label:
        label = args.week_label.strip()
    else:
        run_date = (dt.date.fromisoformat(args.date) if args.date
                    else dt.datetime.now(CENTRAL).date())
        label = fill.week_label(fill.last_sunday(run_date))

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    src = f"CSV {args.csv}" if args.csv else "Tableau (Fiber Lead Performance)"
    print(f"=== Int WoW Penetration % — {label} — {mode} ===")
    print(f"Source: {src}")

    # Seed a failure manifest up-front (live only). If the run crashes mid-way
    # (pull/fill error, or the 'no owners' abort below), it stays ok=false so
    # the orchestrator's verify flags the run INCOMPLETE instead of "ran clean";
    # mark_clean() at the end overwrites it once the fill completes.
    if not args.dry_run:
        try:
            from automations.shared import run_manifest as _rm
            _rm.write_manifest(MANIFEST_ID, failed=["int wow penetration fill"],
                               retry_args=[], kind="int_wow",
                               note="run started but did not complete")
        except Exception:  # noqa: BLE001 — manifest is best-effort, never fail the run
            pass

    # --- data ---
    if args.csv:
        data = pull.parse_csv(Path(args.csv))
    else:
        with tempfile.TemporaryDirectory(prefix="int_wow_") as tmp:
            out = Path(tmp) / "fiber_lead_penetration.csv"
            data = pull.fetch_and_parse(out)

    owners_pct = data["owners"]
    national = data["national"]
    if not owners_pct:
        print("✗ No owners parsed — aborting (nothing to write).")
        return 1

    # --- fill the sheet ---
    aliases = load_aliases()
    if aliases:
        print(f"  Loaded {sum(len(v) for v in aliases.values())} aliases "
              f"({len(aliases)} canonical names).")
    ws = fill.open_ws()
    summary = fill.apply_week(ws, label, owners_pct, national, aliases,
                              dry_run=args.dry_run, force=args.force)

    # --- report ---
    print(f"\n--- summary ({label}) ---")
    print(f"  matched: {summary['matched']}   '-%' filled: {summary['no_data']}"
          f"   national: {summary['national']!r}")
    if summary["new_inserted"]:
        print(f"  + inserted {len(summary['new_inserted'])} new owner(s): "
              f"{summary['new_inserted']}")
    if summary["near_match"]:
        print("  ⚠ NOT inserted — look like existing rows (add an ICD alias?):")
        for csv_name, looks_like in summary["near_match"]:
            print(f"      Tableau {csv_name!r}  ~  sheet {looks_like!r}")
    if data["warnings"]:
        print("  ⚠ pull warnings:")
        for w in data["warnings"]:
            print(f"      {w}")

    # --- Slack note (best-effort; never fails the run) ---
    if args.no_slack:
        print("  (Slack post skipped — --no-slack.)")
    else:
        res = slack_post.post_update(label, dry_run=args.dry_run)
        if args.dry_run:
            pass  # post_update already printed the dry-run line
        elif res.get("ok"):
            print(f"  ✓ Slack: posted to #level10-alphalete thread "
                  f"({res.get('ts')})")
        else:
            print(f"  ⚠ Slack post FAILED (sheet fill is done — run still OK): "
                  f"{res.get('error')}")

    if not args.dry_run:
        try:
            from automations.shared import run_manifest as _rm
            _rm.mark_clean(MANIFEST_ID, kind="int_wow")
        except Exception:  # noqa: BLE001 — manifest is best-effort, never fail the run
            pass

    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
