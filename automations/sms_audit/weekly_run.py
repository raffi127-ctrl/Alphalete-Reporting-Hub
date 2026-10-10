"""The Saturday run — pull all four sources, then write the four tabs.

Megan 2026-09-28: "set up the saturday job". Saturday because the recruiting
week is Sat-Fri (her boundary), so Saturday morning is the first moment the
week that just closed is complete.

ORDER MATTERS, and the last two are not optional. Without the call list and
Email Tracking the "why they didn't book" buckets fall back to text-only,
which measured 55-83% WRONG on 2026-09-28 — every count arithmetically
right and the claim inverted, which is exactly the kind of error nobody
catches by reading the sheet. So a pull that fails is a CORRECTNESS fault
here, not a missing extra, and the summary says so per office.

  lucy rerun sms_audit_weekly --machine "Lucy 2"
  ... weekly_run.py --week 2          # refill a past week
  ... weekly_run.py --skip-pull       # just rewrite the tabs
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9 — keep lazy

import argparse
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
OFFICES = ["11280", "23965", "24065", "11580"]
# (module, args, what breaks without it)
PULLS = [
    ("automations.sms_thread_dump.run", ["--bookings-only"],
     "bookings — the sheet cannot say who booked"),
    ("automations.sms_audit.pull_log", [],
     "texts — the sheet has nothing to read"),
    ("automations.sms_audit.pull_call_list", [],
     "call list — the drop-off buckets revert to text-only and overstate"),
    ("automations.sms_audit.pull_email_tracking", [],
     "email — the drop-off buckets revert to text-only and overstate"),
]


def _py():
    venv = REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def run(module, args):
    import os
    r = subprocess.run([_py(), "-m", module] + args, cwd=str(REPO),
                       capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH="."))
    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-2:]
    for l in tail:
        print("      {}".format(l[:150]), flush=True)
    if r.returncode != 0:
        # the cause is usually on stderr (argparse, a traceback) — without
        # this the log says FAILED and nothing about why
        for l in [l for l in (r.stderr or "").splitlines() if l.strip()][-3:]:
            print("      ! {}".format(l[:150]), flush=True)
    return r.returncode == 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default=",".join(OFFICES))
    ap.add_argument("--week", type=int, default=1)
    ap.add_argument("--skip-pull", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    offices = [o.strip() for o in a.office.split(",") if o.strip()]
    olist = ",".join(offices)

    degraded = []
    if not a.skip_pull:
        for module, extra, breaks in PULLS:
            print("[weekly] {}".format(module), flush=True)
            args = ["--office", olist, "--week", str(a.week)] + list(extra)
            if a.dry_run:
                args.append("--dry-run")
            if not run(module, args):
                print("      FAILED — {}".format(breaks), flush=True)
                degraded.append(breaks)

    rc = 0
    for office in offices:
        args = ["--office", office, "--week", str(a.week)]
        if a.dry_run:
            args.append("--dry-run")
        print("[weekly] sheet {}".format(office), flush=True)
        if not run("automations.sms_audit.weekly_sheet", args):
            rc = 1

    if degraded:
        # Loud, and non-zero: the sheet still wrote, and some of its rows
        # now mean something different from what they say. That is worse
        # than a blank, so it must not read as a clean run.
        print("\n[weekly] WROTE THE SHEET WITH MISSING SOURCES:", flush=True)
        for d in degraded:
            print("   - {}".format(d), flush=True)
        print("   The 'why they didn't book' rows are text-only this week "
              "and will overstate. Re-run the failed pull, then re-run "
              "weekly_sheet.", flush=True)
        rc = 1
    else:
        print("\n[weekly] all four sources pulled; the sheet is on texts, "
              "calls and email.", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
