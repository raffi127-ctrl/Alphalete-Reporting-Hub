"""Noah Dubale's OPT block on the Carlos 1on1s sheet — filled from the NDS/ATT
views, not the B2B ones.

WHY THIS EXISTS (Eve 2026-08-17)
--------------------------------
Noah Dubale (office 23356, Oracle Acquisitions) sits on the *Carlos 1on1s -
Focus Report* roster, but he SELLS NDS. Carlos's own OPT engine
(`opt_phase_carlos`) pulls all six of its views out of `ATTTRACKER-B2B`, so
Noah simply has no source there: his recruiting half fills perfectly (AppStream
sees him) while his whole OPT block comes back empty — churn `No Data In
Tableau` x5, Total Apps 0, Personal Production `-`, headcount blank.

The first read of this was "he moved to B2B, the sources just haven't caught up,
it'll fill itself once Smart Circle moves him". Carlos corrected that on
2026-08-17: **he is still selling NDS and is staying NDS.** So nothing was ever
going to arrive on the B2B side, and waiting was the wrong plan.

The fix is not new code — it's pointing the EXISTING NDS engine at his one tab.
`automations.recruiting_report.opt_phase` is the ATT/NDS OPT phase, it already
writes by column-B label lookup (never hardcoded rows, so Carlos's shifted tab
layout is fine), and it already takes `--only <tab>`. The single thing it needs
that a schedule_config entry cannot give it is `CAPTAINSHIP=Carlos`, which is
what selects Carlos's spreadsheet + mapping. Hence this wrapper — same trick
`carlos_opt_all` uses for its own steps.

DO NOT fold this into carlos_opt_all's step list: that wrapper is the B2B
report, and every other ICD on it is genuinely B2B. This is one NDS exception
riding on a B2B report, and keeping it a separate, separately-runnable step is
what makes that visible.

Usage:
  python -m automations.recruiting_report.carlos_noah_nds --dry-run
  python -m automations.recruiting_report.carlos_noah_nds --week 2026-08-16

Via the mini queue (needs a Tableau session, so it can't run from a laptop
without one):
  lucy rerun carlos_noah_nds --dry-run     # safe probe: writes nothing
  lucy rerun carlos_noah_nds
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# The tab on the Carlos 1on1s sheet. Must match the sheet tab EXACTLY — it is
# also his `sheet_tab` in office-mapping-carlos.json, where his office (23356)
# and as_owner live. If the tab is ever renamed, change it in BOTH places.
NOAH_TAB = "Noah Dubale"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fill Noah Dubale's OPT block on Carlos 1on1s from the "
                    "NDS/ATT views (he sells NDS, not B2B).")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD. "
                                   "Default: most recent Sunday.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Download + report what WOULD be written; no Sheet "
                         "writes. Run this first.")
    args = ap.parse_args()

    # CAPTAINSHIP is what points the shared recruiting_report modules at
    # Carlos's spreadsheet + office-mapping-carlos.json. opt_phase has no
    # --captainship flag, and schedule_config has no way to set env, so it goes
    # on the subprocess env here.
    env = {**os.environ, "CAPTAINSHIP": "Carlos"}
    cmd = [sys.executable, "-u", "-m", "automations.recruiting_report.opt_phase",
           "--only", NOAH_TAB]
    if args.week:
        cmd += ["--week", args.week]
    if args.dry_run:
        cmd.append("--dry-run")
    # --skip-breakdowns: the production/team breakdowns are a whole-report tail
    # step. This run touches ONE tab, so re-running them here would redo work
    # the real Carlos run already did (and on a partial picture).
    cmd.append("--skip-breakdowns")

    print(f"=== Noah Dubale — NDS OPT onto Carlos 1on1s "
          f"({'DRY RUN' if args.dry_run else 'LIVE'}) ===", flush=True)
    print(f"    tab={NOAH_TAB!r}  week={args.week or 'most recent Sunday'}",
          flush=True)
    rc = subprocess.run(cmd, env=env).returncode

    if rc != 0:
        print(f"\n✗ exit {rc} — see the log above.", flush=True)
        return rc
    # A clean exit does NOT prove his numbers arrived: opt_phase writes what the
    # views gave it, and if Noah is absent from the NDS crosstabs the run is
    # "successful" with an empty tab — the exact failure mode that made his
    # block look broken on the B2B side. So say it out loud rather than let a
    # green exit imply data landed.
    print("\n✓ done. CHECK THE TAB: a clean exit only means the run finished, "
          "not that Noah was present in the NDS views. If his OPT rows are "
          "still blank, he isn't in those crosstabs either and the source "
          "question goes back to Smart Circle.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
