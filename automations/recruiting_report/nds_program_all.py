"""NDS Program - Focus Report — the whole weekly fill in one run.

Rafael 2026-09-22: a Focus Report like the fiber one, with a tab for every
owner in the NDS tracker (not just our org's). Two steps, same shape as
alphalete_org_report.opt_all:

  1. Recruiting pull (AppStream) for the owners whose office we can see —
     CAPTAINSHIP=NDS-Program points the shared recruiting_report modules at
     this workbook and its office mapping. The owners with no visible office
     sit in that mapping's `skip` list and carry 'No access to this office'
     in A22; the step never touches them.
  2. NDS OPT (Tableau) with --sheet-id, i.e. the engine that fills the org's
     '<owner> - NDS' tabs, pointed at this workbook.

MONDAYS ONLY, and that is not a preference: the NDS tracker has no date
control, so Active Selling Heads / Scorecard Ranking / National AVG — and,
for the owners Sara Plus does not carry, New Lines and AIR — are only ever
the just-closed week's numbers on a Monday morning. Run it on a Tuesday and
those cells get the in-progress week written under last week's column (it
happened on 2026-09-22; the values had to be cleared by hand). Eve confirmed
the same day: "si los focus reports siempre se completan los lunes".

Each step is its own subprocess, so one failing never aborts the other.

    python -m automations.recruiting_report.nds_program_all
    python -m automations.recruiting_report.nds_program_all --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys

SHEET_ID = "1Vu_J7bcSpreIBcsYuAVEQMusL9-RaOSgB65DiKxrYtI"
CAPTAINSHIP = "NDS-Program"


def _last_sunday(today: dt.date | None = None) -> dt.date:
    """The week-ending Sunday the sheet's columns are keyed by. On a Monday
    that is yesterday — the week this run is reporting on."""
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7 or 7)


def _step(name: str, cmd: list[str], env: dict | None = None) -> int:
    print(f"\n{'=' * 64}\n=== {name} ===\n{'=' * 64}", flush=True)
    try:
        return subprocess.run(cmd, env=env).returncode
    except Exception as e:  # noqa: BLE001 — a launch failure must not abort
        print(f"x {name}: couldn't start - {type(e).__name__}: {e}", flush=True)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="WE Sunday (YYYY-MM-DD). Default: the most "
                                   "recent Sunday.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pass --dry-run to every step (no Sheet writes).")
    args = ap.parse_args()

    week = args.week or _last_sunday().isoformat()
    py = [sys.executable, "-u", "-m"]
    dry = ["--dry-run"] if args.dry_run else []

    steps = [
        ("Recruiting pull (AppStream)",
         py + ["automations.recruiting_report.run", "--no-opt",
               "--week", week] + dry,
         {**os.environ, "CAPTAINSHIP": CAPTAINSHIP}),
        ("NDS OPT (Tableau)",
         py + ["automations.alphalete_org_report.opt_nds",
               "--sheet-id", SHEET_ID] + dry,
         None),
    ]

    results = [(name, _step(name, cmd, env)) for name, cmd, env in steps]

    print(f"\n{'=' * 64}\n=== NDS Program - Focus Report: summary ===\n"
          f"{'=' * 64}", flush=True)
    for name, rc in results:
        print(f"  {'OK ' if rc == 0 else 'FAIL'} {name}"
              + ("" if rc == 0 else f" (exit {rc})"), flush=True)
    # Exit 0 even when a step failed: the other step's fill is real work, and
    # the summary above already names what to re-run. Same call opt_all makes.
    return 0


if __name__ == "__main__":
    sys.exit(main())
