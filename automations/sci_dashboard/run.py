"""SCI Recruiting Dashboard — run the recruiting reports against the SCI book.

The captainship split (Carlos 2026-10-02): the 15 captainship-only owners
report in their own workbook, the SCI Recruiting Dashboard
(1aWWdtMtv1ivZa8fv10cbEzJJUNrO7h9YA8fVvfiRqlg), with the same three modules
the Alphalete book uses. The deploy wrappers (funnel_board_hourly.sh,
indeed_source_report.sh, ad_sales_board.sh) already run an SCI pass after
every Alphalete pass, so the schedules cover both books on their own.

This module exists for the QUEUE: `lucy rerun` can only name a registry
module and cannot set env vars, and the SCI pass is nothing but env vars —
the SCI sheet id plus the deploy/sci-roster.json roster override. So this
sets that env and runs the report modules in sequence, one AppStream login
at a time, same order as the 1am chain.

    lucy rerun sci_recruiting                  -> funnel + indeed + ad sales
    lucy rerun sci_recruiting --steps funnel   -> just one of them
    lucy rerun sci_recruiting --dry-run        -> unknown args forward to
                                                  every step it runs

Monday close-out, the restatement rule, discovery for blank office ids
(Nicolas Lujan) all live in the report modules themselves and behave here
exactly as they do on the Alphalete pass.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCI_SSID = "1aWWdtMtv1ivZa8fv10cbEzJJUNrO7h9YA8fVvfiRqlg"
ROSTER = REPO / "deploy" / "sci-roster.json"
MODULES = {"funnel": "automations.funnel_board.run",
           "indeed": "automations.indeed_source_report.run",
           "adsales": "automations.ad_sales_board.run"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", default="funnel,indeed,adsales",
                    help="comma list from: funnel, indeed, adsales")
    a, extra = ap.parse_known_args(argv)
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    bad = [s for s in steps if s not in MODULES]
    if bad:
        print("unknown step(s): %s (want: %s)" % (bad, list(MODULES)))
        return 2
    if not ROSTER.exists():
        print("missing %s — the SCI pass must never fall back to the "
              "Alphalete roster" % ROSTER)
        return 2
    env = dict(os.environ,
               FUNNEL_SSID=SCI_SSID,
               INDEED_SOURCE_SPREADSHEET_ID=SCI_SSID,
               RECRUITING_ROSTER_JSON=str(ROSTER))
    rc_all = 0
    for key in steps:
        print("== SCI %s (%s) ==" % (key, MODULES[key]), flush=True)
        rc = subprocess.call([sys.executable, "-u", "-m", MODULES[key]] + extra,
                             env=env, cwd=str(REPO))
        print("== SCI %s exit=%d ==" % (key, rc), flush=True)
        rc_all = rc_all or rc
    return rc_all


if __name__ == "__main__":
    raise SystemExit(main())
