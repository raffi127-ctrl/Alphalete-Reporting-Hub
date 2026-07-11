"""Pull Rashad's New Internet ABP% into his dedicated 'Metrics Reports -
Rashad Reed' sheet, mirroring rashad_metrics.churn_pull.

Points the SHARED ABP report (automations.new_internet_abp.run) at
Rashad's Tableau view + sheet + owner via env overrides, then runs it.
Raf's ABP is untouched — the overrides default to Raf's values when
unset, so this only changes the run when these env vars are present.

  ABP_NI_VIEW_URL   → RashadNLABP (New Internet ABP, owner = Rashad Reed;
                      the 'NL' in the view name is legacy — Megan updated
                      it to the New Internet ABP view, verified 2026-07-10)
  ABP_SHEET_ID      → Metrics Reports - Rashad Reed
  ABP_OWNER         → RASHAD REED
  METRICS_CHANNEL_ID→ C0B3KTCCMT7 (#elevate-sales) for the Slack post

Default is --skip-slack (fill the sheet, NO Slack post) — the first run
just bootstraps his tab; wire the #elevate-sales post later (or pass no
--skip-slack on a --live run). Needs a 'Local Office - New Internet ABP%'
tab on his sheet first. Pass other new_internet_abp args through
(--dry-run, --force-insert, --skip-download).

Run on the MINI (the ownerville→Tableau session lives there):
    python -m automations.rashad_metrics.abp_pull            # fill sheet, no post
    python -m automations.rashad_metrics.abp_pull --dry-run  # pull, no write
    python -m automations.rashad_metrics.abp_pull --post     # fill + post to #elevate-sales
"""
from __future__ import annotations

import os
import subprocess
import sys

NI_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
           "ATTTRACKER2_1-D2D/Metrics/"
           "d932e0f6-72b4-4003-a5d1-4262137363de/RashadNLABP?:iid=1")
SHEET_ID = "11louWIU8IuSPrZLsMkRh8qEnO3wNqmeNwIOSKPpXzm8"
OWNER = "RASHAD REED"
ELEVATE_CHANNEL_ID = "C0B3KTCCMT7"   # #elevate-sales — PRIVATE


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    env = dict(os.environ,
               ABP_NI_VIEW_URL=NI_VIEW,
               ABP_SHEET_ID=SHEET_ID,
               ABP_OWNER=OWNER,
               METRICS_CHANNEL_ID=ELEVATE_CHANNEL_ID)
    # --post opts INTO the Slack post; default is sheet-only (--skip-slack).
    if "--post" in argv:
        argv.remove("--post")
        args = argv
    else:
        args = argv + (["--skip-slack"] if "--skip-slack" not in argv
                       and "--dry-run" not in argv else [])
    cmd = [sys.executable, "-u", "-m", "automations.new_internet_abp.run", *args]
    print("Rashad ABP → 'Metrics Reports - Rashad Reed' "
          f"({SHEET_ID})\n  view: RashadNLABP  owner: {OWNER}\n  $ {' '.join(cmd)}",
          flush=True)
    return subprocess.run(cmd, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
