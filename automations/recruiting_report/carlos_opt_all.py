"""Carlos 1on1s — the FULL weekly fill in one run.

The Carlos card used to run the shared recruiting_report.run WITH the main ATT
opt_phase, but Carlos's B2B owners aren't in the ATT/INT views, so the OPT phase
skipped all 33 tabs and crashed the Production Breakdown (glitch 2026-06-01).
Carlos's real OPT lives in opt_phase_carlos, which fills the B2B views ONE AT A
TIME (--apply-view <key>). This wrapper chains the whole report:

  1. Recruiting pull (AppStream -> every Carlos ICD tab)   [--no-opt]
  2-8. Each Carlos OPT view (opt_phase_carlos --apply-view <key>) — B2B
       1-Pager, Cancel Rates, Activation, Churn, Penetration, Personal
       Production, Direct Deposit.

Mirrors automations/alphalete_org_report/opt_all: each step is its OWN
subprocess so one failing view can NEVER abort the rest, and a per-step summary
flags what to re-run. CAPTAINSHIP=Carlos is set on every step so the shared
recruiting_report module points at Carlos's sheet/mapping. The OPT views
auto-target the current week internally, so only the recruiting step takes
--week.

Usage (the Hub runs this; --week comes from the card's args_fn):
  python -m automations.recruiting_report.carlos_opt_all --week 2026-05-24
  python -m automations.recruiting_report.carlos_opt_all --week 2026-05-24 --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Order matters only for readability — each runs independently. Keys must match
# opt_phase_carlos.VIEWS.
CARLOS_OPT_VIEWS = [
    ("B2B 1-Pager",        "d2d1"),
    ("Cancel Rates",       "cancel"),
    ("Activation",         "activation"),
    ("Churn",              "churn"),
    ("Penetration",        "penetration"),
    ("Personal Production", "personal_production"),
    ("Direct Deposit",     "dd"),
]


def _step(name: str, cmd: list[str], env: dict | None = None) -> int:
    """Run one step as a subprocess, streaming output to this run's log.
    Returns the exit code (0 = ok). Never raises — a launch failure returns 1
    so the chain keeps going."""
    print(f"\n{'=' * 64}\n=== {name} ===\n{'=' * 64}", flush=True)
    try:
        return subprocess.run(cmd, env=env).returncode
    except Exception as e:
        print(f"✗ {name}: couldn't start — {type(e).__name__}: {e}", flush=True)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="WE Sunday (YYYY-MM-DD) for the recruiting pull.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pass --dry-run to every step (no Sheet writes).")
    args = ap.parse_args()

    py = [sys.executable, "-u", "-m"]
    dry = ["--dry-run"] if args.dry_run else []
    env = {**os.environ, "CAPTAINSHIP": "Carlos"}

    rec_cmd = (py + ["automations.recruiting_report.run", "--no-opt"]
               + (["--week", args.week] if args.week else []) + dry)
    steps = [("Recruiting pull", rec_cmd)]
    for label, key in CARLOS_OPT_VIEWS:
        steps.append((f"OPT view — {label}",
                      py + ["automations.recruiting_report.opt_phase_carlos",
                            "--apply-view", key] + dry))

    results = [(name, _step(name, cmd, env)) for name, cmd in steps]

    print(f"\n{'=' * 64}\n=== Carlos 1on1s — full run summary ===\n{'=' * 64}",
          flush=True)
    any_fail = False
    for name, rc in results:
        if rc != 0:
            any_fail = True
        print(f"  {'✅' if rc == 0 else '❌'} {name}"
              + ("" if rc == 0 else f" (exit {rc})"), flush=True)
    if any_fail:
        print("\n⚠️ One or more steps failed — see the logs above. The steps "
              "that succeeded DID fill; re-run a failed view with "
              "`opt_phase_carlos --apply-view <key>`.", flush=True)
    # Exit 0 even if a step failed: the run as a whole did useful work, and the
    # per-step summary flags what to re-run.
    return 0


if __name__ == "__main__":
    sys.exit(main())
