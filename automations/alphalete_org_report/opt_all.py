"""Alphalete Org — the FULL weekly fill in one run.

Megan 2026-05-25: "there are NO 5 separate runs on that — chain them." The
Alphalete Org card's "Run This Week" used to fill only the recruiting section
(it ran recruiting_report.run with --no-opt) and left the five OPT pulls as
separate buttons. This wrapper chains the whole report into one run:

  1. Recruiting pull (AppStream -> every visible rep tab)   [needs Report Chrome]
  2. NDS OPT     (Tableau via patchright)
  3. BOX OPT     (Tableau B2B BOX Energy via patchright)
  4. JE OPT      (Tableau via patchright)
  5. B2B OPT     (ATTTRACKER-B2B via patchright)
  6. Retail OPT  (Tableau via patchright; Report Chrome on current main)

Each step runs as its own subprocess so one step failing can NEVER abort the
rest — a step that succeeds still fills its section. A summary at the end lists
which steps passed/failed so a single failure can be re-run from its own button.

The OPT modules auto-target the current week internally, so only the
recruiting step takes --week. (Past-week catch-ups stay recruiting-only on the
'Run a Specific Past Week' button — the OPT trackers are current-week only.)

Usage (the Hub runs this; --week comes from the card's args_fn):
  python -m automations.alphalete_org_report.opt_all --week 2026-05-24
  python -m automations.alphalete_org_report.opt_all --week 2026-05-24 --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Orchestrator-completeness manifest id (matches the scheduler's verify.report_id
# for alphalete_org_focus). Distinct from the Hub card id 'recruiting-alphalete-org'.
MANIFEST_ID = "alphalete-org-run"


def _step(name: str, cmd: list[str], env: dict | None = None) -> int:
    """Run one step as a subprocess, streaming its output to this run's log.
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

    # The recruiting pull needs CAPTAINSHIP=Alphalete-Org so the shared
    # recruiting_report module points at the Org sheet/mapping. The Hub already
    # sets this on the subprocess env, but set it explicitly too so this works
    # however it's launched.
    rec_env = {**os.environ, "CAPTAINSHIP": "Alphalete-Org"}
    rec_cmd = (py + ["automations.recruiting_report.run", "--no-opt"]
               + (["--week", args.week] if args.week else []) + dry)

    steps = [
        ("Recruiting pull", rec_cmd, rec_env),
        ("NDS OPT",    py + ["automations.alphalete_org_report.opt_nds"] + dry, None),
        ("BOX OPT",    py + ["automations.alphalete_org_report.opt_box"] + dry, None),
        ("JE OPT",     py + ["automations.alphalete_org_report.opt_je"] + dry, None),
        ("B2B OPT",    py + ["automations.alphalete_org_report.opt_b2b"] + dry, None),
        ("Retail OPT", py + ["automations.alphalete_org_report.opt_retail"] + dry, None),
    ]

    results: list[tuple[str, int]] = []
    for name, cmd, env in steps:
        results.append((name, _step(name, cmd, env)))

    print(f"\n{'=' * 64}\n=== Alphalete Org — full run summary ===\n{'=' * 64}",
          flush=True)
    any_fail = False
    for name, rc in results:
        if rc != 0:
            any_fail = True
        print(f"  {'✅' if rc == 0 else '❌'} {name}"
              + ("" if rc == 0 else f" (exit {rc})"), flush=True)
    if any_fail:
        print("\n⚠️ One or more steps failed — see the logs above. The steps "
              "that succeeded DID fill; re-run only the failed one from its own "
              "button on the card.", flush=True)

    # Orchestrator-completeness manifest (SEPARATE from the Hub card's
    # 'recruiting-alphalete-org' manifest the recruiting sub-step writes — don't
    # clobber that). Because this wrapper always exits 0 (so partial success
    # isn't hidden), the day-orchestrator can't tell from the exit code that a
    # step silently failed; this manifest lets verify report INCOMPLETE and name
    # the failed steps. Best-effort + only on a real (non-dry) run.
    if not args.dry_run:
        try:
            from automations.shared import run_manifest as _rm
            failed = [name for name, rc in results if rc != 0]
            if failed:
                _rm.write_manifest(
                    MANIFEST_ID, failed=failed, retry_args=[], kind="step",
                    note=f"{len(failed)} of {len(results)} step(s) failed: "
                         + ", ".join(failed) + ". Re-run each from its card button.")
            else:
                _rm.mark_clean(MANIFEST_ID, kind="step")
        except Exception:  # noqa: BLE001 — manifest is best-effort
            pass

    # Exit 0 even if a step failed: the run as a whole did useful work, and the
    # per-step summary already flags what to re-run. (Returning non-zero would
    # mark the whole run failed and hide the partial success.)
    return 0


if __name__ == "__main__":
    sys.exit(main())
