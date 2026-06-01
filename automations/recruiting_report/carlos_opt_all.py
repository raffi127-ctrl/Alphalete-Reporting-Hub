"""Carlos 1on1s — the FULL weekly fill in one run.

The Carlos card used to run the shared recruiting_report.run WITH the main ATT
opt_phase, but Carlos's B2B owners aren't in the ATT/INT views, so the OPT phase
skipped all 33 tabs and crashed the Production Breakdown (glitch 2026-06-01).
Carlos's real OPT lives in opt_phase_carlos. Each view is downloaded
(--test-view <key>) THEN applied (--apply-view <key>) — apply only reads the
cached CSV that download writes, so the download must run first. (Direct
Deposit is the exception: its apply path scrapes inline, no separate download.)
This wrapper chains the whole report:

  1. Recruiting pull (AppStream -> every Carlos ICD tab)   [--no-opt]
  2-8. Each Carlos OPT view: download (--test-view) then apply (--apply-view) —
       B2B 1-Pager, Cancel Rates, Activation, Churn, Penetration, Personal
       Production, Direct Deposit.

Each step is its OWN subprocess in its OWN PROCESS GROUP. The process-group
isolation is critical on Windows: when a step's patchright/Chrome closes it can
raise a console CTRL_BREAK that, without isolation, propagates to THIS parent
and kills the chain right after the recruiting step "done" (glitch 2026-06-01,
Eve's Windows run — the OPT views never ran). With CREATE_NEW_PROCESS_GROUP the
signal stays inside the child. Every step is also wrapped in catch-everything +
explicit markers so a stop point is always visible in the log.

CAPTAINSHIP=Carlos is set on every step so the shared recruiting_report module
points at Carlos's sheet/mapping. The OPT views auto-target the current week, so
only the recruiting step takes --week.

Usage (the Hub runs this; --week comes from the card's args_fn):
  python -m automations.recruiting_report.carlos_opt_all --week 2026-05-24
  python -m automations.recruiting_report.carlos_opt_all --week 2026-05-24 --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

CARLOS_OPT_VIEWS = [
    ("B2B 1-Pager",        "d2d1"),
    ("Cancel Rates",       "cancel"),
    ("Activation",         "activation"),
    ("Churn",              "churn"),
    ("Penetration",        "penetration"),
    ("Personal Production", "personal_production"),
    ("Direct Deposit",     "dd"),
]

# Windows: give each step its own process group so a child's console
# CTRL_BREAK (patchright/Chrome teardown) can't propagate up and kill us.
_POPEN_KW = {}
if os.name == "nt":
    _POPEN_KW["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP


def _step(name: str, cmd: list[str], env: dict | None = None) -> int:
    """Run one step as a subprocess in its own process group, streaming output
    to this run's log. Returns the exit code (0 = ok). NEVER raises — catches
    everything (incl. KeyboardInterrupt/console signals) so the chain always
    continues to the next step."""
    print(f"\n{'=' * 64}\n=== {name} ===\n{'=' * 64}", flush=True)
    try:
        return subprocess.run(cmd, env=env, **_POPEN_KW).returncode
    except BaseException as e:   # noqa: BLE001 — keep the chain alive no matter what
        print(f"✗ {name}: {type(e).__name__}: {e}", flush=True)
        return 1


def _run_view(label: str, key: str, py: list[str], dry: list[str],
              env: dict | None = None) -> tuple[str, int]:
    """Download then apply one Carlos OPT view as a single logical step.

    `--apply-view` only reads the cached CSV under output/carlos_opt_downloads/;
    it does NOT download. So we run `--test-view <key>` first to populate that
    cache, then `--apply-view <key>` to write the Sheet. Direct Deposit ('dd')
    is the exception — its apply path scrapes View Data inline, so it skips the
    download. If the download fails, the apply is skipped (it could only fail
    too on an empty cache). Returns (display_name, exit_code)."""
    name = f"OPT view — {label}"
    mod = "automations.recruiting_report.opt_phase_carlos"
    if key != "dd":
        rc = _step(f"{name} (download)", py + [mod, "--test-view", key], env)
        if rc != 0:
            return (name, rc)
    rc = _step(f"{name} (apply)", py + [mod, "--apply-view", key] + dry, env)
    return (name, rc)


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

    print(f"Carlos full run: recruiting + {len(CARLOS_OPT_VIEWS)} OPT views "
          f"(each view = download then apply). This keeps going for ~15 min "
          f"AFTER the recruiting 'done' — do NOT stop it early.", flush=True)

    results = [("Recruiting pull", _step("Recruiting pull", rec_cmd, env))]
    for label, key in CARLOS_OPT_VIEWS:
        results.append(_run_view(label, key, py, dry, env))

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
              "that succeeded DID fill; re-run a failed view by re-running "
              "this wrapper, or manually with `opt_phase_carlos --test-view "
              "<key>` then `--apply-view <key>`.", flush=True)
    # Exit 0 even if a step failed: the run as a whole did useful work, and the
    # per-step summary flags what to re-run.
    return 0


if __name__ == "__main__":
    sys.exit(main())
