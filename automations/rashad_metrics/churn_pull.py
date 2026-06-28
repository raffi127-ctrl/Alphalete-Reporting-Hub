"""Pull Rashad's churn into his dedicated 'Metrics Reports - Rashad Reed' sheet.

Points the SHARED churn fill (automations.churn.run) at Rashad's Tableau views +
sheet via env overrides, then runs it. Raf's churn is untouched — the overrides
default to Raf's values when unset, so this only changes the run when these env
vars are present.

  CHURN_NI_VIEW_URL → INTRashad        (New Internet churn, owner = Rashad Reed)
  CHURN_WL_VIEW_URL → WirelessRashad   (Wireless churn)
  CHURN_SHEET_ID    → Metrics Reports - Rashad Reed

Default is --skip-slack (fill the sheet, NO Slack post) — the first seed just
populates today's column; wire the #elevate-sales post later. Pass other churn
args through (e.g. --dry-run, --only new-internet).

Run on the MINI (the ownerville→Tableau session lives there):
    python -m automations.rashad_metrics.churn_pull            # both, sheet-only
    python -m automations.rashad_metrics.churn_pull --dry-run  # pull, no write
"""
from __future__ import annotations

import os
import subprocess
import sys

NI_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
           "ATTTRACKER2_1-D2D/CHURN/"
           "39c6f9f5-77c8-4de6-909e-5db242f9ee4a/INTRashad?:iid=1")
WL_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
           "ATTTRACKER2_1-D2D/CHURN/"
           "2a80ee2a-7471-47ae-a592-27832a6e0ff5/WirelessRashad?:iid=1")
SHEET_ID = "11louWIU8IuSPrZLsMkRh8qEnO3wNqmeNwIOSKPpXzm8"


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    env = dict(os.environ,
               CHURN_NI_VIEW_URL=NI_VIEW,
               CHURN_WL_VIEW_URL=WL_VIEW,
               CHURN_SHEET_ID=SHEET_ID)
    args = argv if argv else ["--skip-slack"]   # default: fill the sheet, no Slack
    cmd = [sys.executable, "-u", "-m", "automations.churn.run", *args]
    print("Rashad churn → 'Metrics Reports - Rashad Reed' "
          f"({SHEET_ID})\n  views: INTRashad + WirelessRashad\n  $ {' '.join(cmd)}",
          flush=True)
    return subprocess.run(cmd, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
