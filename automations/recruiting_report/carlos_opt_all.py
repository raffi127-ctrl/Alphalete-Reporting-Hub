"""Carlos 1on1s — the FULL weekly fill in one run.

The Carlos card used to run the shared recruiting_report.run WITH the main ATT
opt_phase, but Carlos's B2B owners aren't in the ATT/INT views, so the OPT phase
skipped all 33 tabs and crashed the Production Breakdown (glitch 2026-06-01).
Carlos's real OPT lives in opt_phase_carlos. ALL views are downloaded under a
SINGLE ownerville login (--download-all), then each is applied from its cached
CSV (--apply-view <key> --no-download) with no further logins. The old flow
logged in once PER view (a fresh browser each time), which tripped ownerville's
Cloudflare challenge so the login click never completed (Eve 2026-06-01). This
wrapper chains the whole report:

  1. Recruiting pull (AppStream -> every Carlos ICD tab)   [--no-opt]
  2. Download ALL OPT views in one login (--download-all) — B2B 1-Pager, Cancel
     Rates, Activation, Churn, Penetration, Personal Production (crosstabs) +
     Direct Deposit (View Data scrape), all on one shared page.
  3-9. Apply each view from cache (--apply-view <key> --no-download).

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
import time

# Orchestrator-completeness manifest id (matches the scheduler's verify.report_id
# for carlos_focus). Distinct from the Hub card id 'recruiting-carlos'.
MANIFEST_ID = "carlos-1on1s-run"

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

    print(f"Carlos full run: recruiting → ONE-login download of all "
          f"{len(CARLOS_OPT_VIEWS)} OPT views → apply each from cache. "
          f"This keeps going for ~15 min AFTER the recruiting 'done' — do "
          f"NOT stop it early.", flush=True)

    mod = "automations.recruiting_report.opt_phase_carlos"
    results = [("Recruiting pull", _step("Recruiting pull", rec_cmd, env))]

    # ONE ownerville login: download every OPT view's data to the cache.
    # Per-view logins (a browser per view) were tripping Cloudflare so the
    # login click never completed (Eve 2026-06-01). If this step fails, the
    # apply steps below still run against whatever cache exists and the
    # summary flags it.
    results.append(("Download all OPT views (one login)",
                    _step("Download all OPT views (one login)",
                          py + [mod, "--download-all"], env)))

    # Apply each view from the cache — no further ownerville logins.
    # Apply from cache, back-to-back. Each apply writes ~33 cells (one per ICD
    # tab); firing them with no gap blows past Google Sheets' "write requests
    # per minute per user" cap → 429 on later views (the old per-view flow
    # never hit this because each download interleaved natural delay). Pause
    # between applies to stay under the quota.
    APPLY_GAP_SEC = 45
    for i, (label, key) in enumerate(CARLOS_OPT_VIEWS):
        if i:
            time.sleep(APPLY_GAP_SEC)
        rc = _step(f"OPT view — {label} (apply)",
                   py + [mod, "--apply-view", key, "--no-download"] + dry, env)
        results.append((f"OPT view — {label}", rc))

    print(f"\n{'=' * 64}\n=== Carlos 1on1s — full run summary ===\n{'=' * 64}",
          flush=True)
    any_fail = False
    for name, rc in results:
        if rc != 0:
            any_fail = True
        print(f"  {'✅' if rc == 0 else '❌'} {name}"
              + ("" if rc == 0 else f" (exit {rc})"), flush=True)
    if any_fail:
        print("\n⚠️ One or more steps FAILED — see the logs above. The steps "
              "that succeeded DID fill; re-run this wrapper, or manually with "
              "`opt_phase_carlos --download-all` then `--apply-view <key> "
              "--no-download` per view.", flush=True)

    # Orchestrator-completeness manifest (SEPARATE from the Hub card's
    # 'recruiting-carlos' id). This wrapper always exits 0 so partial success
    # isn't hidden — which also means the day-orchestrator can't see a silent
    # step failure from the exit code. This manifest lets verify report
    # INCOMPLETE + name the failed steps. Best-effort, real (non-dry) runs only.
    if not args.dry_run:
        try:
            from automations.shared import run_manifest as _rm
            failed = [name for name, rc in results if rc != 0]
            if failed:
                _rm.write_manifest(
                    MANIFEST_ID, failed=failed, retry_args=[], kind="step",
                    note=f"{len(failed)} of {len(results)} step(s) failed: "
                         + ", ".join(failed) + ". Re-run the wrapper or each view.")
            else:
                _rm.mark_clean(MANIFEST_ID, kind="step")
        except Exception:  # noqa: BLE001 — manifest is best-effort
            pass

    if not any_fail:
        # Authoritative success sentinel. The Hub classifies a run as success
        # ONLY when it sees '=== done ===' (checked BEFORE the traceback scan),
        # so a fully-successful run is no longer mis-filed as a glitch just
        # because a recovered, non-fatal error printed a traceback earlier in
        # the log (e.g. a per-ICD retry inside the recruiting pull). When a
        # step truly fails we deliberately DON'T print this — the 'FAILED'
        # line above keeps the run classified as failed so a real break still
        # files a glitch.
        print("\n=== done ===", flush=True)
    # Exit 0 even if a step failed: the run as a whole did useful work, and the
    # per-step summary flags what to re-run.
    return 0


if __name__ == "__main__":
    sys.exit(main())
