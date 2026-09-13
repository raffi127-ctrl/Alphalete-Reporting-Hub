"""Retail JE daily headcount off the JE REP Scorecard — Eve's rule, 2026-09-12.

THE RULE. Tableau `JEWeeklyTracker_17559651319030` -> view `JEREPScorecard`.
Pick the 'ICD Owner' filter = the owner, and COUNT how many reps belong to that
owner — the number is not printed in any column, it is a count of rep rows. The
next day, the same. The workbook only shows the CURRENT week, so JE has no
history to recover: the breakdown is collected day by day from the first run.

THIS FIRST VERSION ONLY PROBES. Nobody has looked at this view from code yet, so
before a count is trusted we need to see what its .csv export actually carries:
which columns, whether 'ICD Owner' is one of them (one download for every owner)
or the filter has to be driven per owner, and what dates it covers. `--probe`
downloads the export once and copies its header + rows into the 'HC JE Probe'
tab of the Mini Control workbook (a laptop can read that; `logtail` returns 470
characters). It writes nothing to the headcount board.

    python -m automations.org_active_headcount.je_scorecard --probe
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "output" / "_hc_je"
WORKBOOK = "JEWeeklyTracker_17559651319030"
VIEW = "JEREPScorecard"
PROBE_TAB = "HC JE Probe"
OWNER_FILTER = "ICD Owner"


def download(params=None) -> Path:
    from automations.alphalete_org_report.tableau_http import download_view_csv
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return download_view_csv(WORKBOOK, VIEW, OUT / f"je_rep_scorecard_{stamp}.csv",
                             params=params)


def probe() -> None:
    # Pulling a view this way passes the freshness gate, which would open a
    # staleness thread for a view nothing reads yet (see
    # project_je-opt-monday-fill-misses-sunday: probes dirtied that thread).
    os.environ.setdefault("ALPHALETE_SKIP_FRESHNESS", "1")
    from automations.alphalete_org_report.tableau_http import parse_csv
    rows_out = []
    for label, params in (("no filter", None),
                          ("ICD Owner=Brandon Stallkamp", {OWNER_FILTER: "Brandon Stallkamp"})):
        try:
            path = download(params)
            rows = parse_csv(path)
            print(f"{label}: {path.name}, {len(rows)} row(s)", flush=True)
            rows_out.append([f"== {label}", path.name, f"{len(rows)} rows"])
            rows_out.extend(rows[:400])
        except Exception as e:                                     # noqa: BLE001
            print(f"{label}: FAILED {type(e).__name__}: {e}", flush=True)
            rows_out.append([f"== {label}", "FAILED", f"{type(e).__name__}: {e}"[:300]])
    _to_sheet(PROBE_TAB, rows_out)


def _to_sheet(title, rows) -> None:
    from automations.org_active_headcount.tracker_readings import _to_sheet as write
    write(title, rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true",
                    help="download the export and copy it to the 'HC JE Probe' tab")
    a = ap.parse_args(argv)
    if not a.probe:
        ap.error("only --probe exists so far")
    probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
