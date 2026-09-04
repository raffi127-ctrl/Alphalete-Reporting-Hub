"""Is a UNIT TEST driving this call? Then don't do the irreversible thing.

WHY THIS EXISTS (2026-09-04). `#claudecorrections-and-requests` carried an
incident called **"R failed"** — report_id `r`, machine MacBook-Pro-3.local —
open for a day, with Lucy's own note saying automatic retries had not fixed it
and re-running would not either. She was right, for a reason nobody could have
guessed from the channel: **there is no report `r`.** It is the fixture in
`automations/day_orchestrator/test_probe_reason.py`:

    mini_control._publish_rerun_done("r", "R", ok, "run-1", probe)

That test installs a fake `hub_publish` through `sys.modules` only. But
`_publish_rerun_done` does `from automations.day_orchestrator import
hub_publish`, which — once anything in the process has genuinely imported that
submodule — resolves through the PACKAGE ATTRIBUTE, not `sys.modules`. So in a
full-suite run the stub is silently bypassed and the REAL `publish_done` runs
with `status="failed"`, `alert_on_fail=True`. It posted a live 🚨, opened a real
incident thread, appended a real Hub activity row stamped with the laptop's
hostname, and auto-created a phantom Hub library card `r`. Three days of a
person's attention were pointed at a test fixture.

(The identical import trap is documented in
`automations/b2b_metrics/test_manifest_merge._stubbed`, which patches the
package attribute for exactly this reason. That test got it right; this one did
not — which is the point: the fix must not depend on every future test author
remembering.)

So this is the SECOND lock, under the first. The test is fixed, and on top of
that the handful of genuinely outward, irreversible effects refuse to fire when
a unit test is on the call stack:

  * posting a failure alert / opening an incident thread
  * closing someone else's incident with a ✅
  * auto-creating a Hub library card

WHY THE STACK AND NOT AN ENV VAR. `unittest` being importable says nothing — a
report can import it transitively. A frame whose module is `unittest.something`
is only ever on the stack when a test runner is actually driving, and never in a
4am report. It cannot false-positive on production and it needs no test author
to remember to set anything.

DELIBERATELY NARROW. This does NOT gate ordinary Hub writes: several real tests
drive `publish_running` / `publish_done` with the sheet stubbed and assert on
what came back, and they must keep working. It gates only what reaches a human
or leaves a permanent mark. See [[feedback_no_blind_test_sweeps]] — some
`test_*.py` in this repo send for real, and this is the structural half of that
rule.
"""
from __future__ import annotations

import sys


def driven_by_a_test() -> bool:
    """True when a unit-test runner is on the call stack right now.

    Walks frames rather than sniffing the environment: only a real test run puts
    a `unittest.*` frame below the caller, so a scheduled report can never trip
    this and a test can never miss it by forgetting a flag."""
    try:
        frame = sys._getframe(1)
    except Exception:  # noqa: BLE001 — no frame introspection: assume production
        return False
    while frame is not None:
        name = frame.f_globals.get("__name__") or ""
        if name == "unittest" or name.startswith("unittest."):
            return True
        frame = frame.f_back
    return False


def refuse_if_under_test(what: str, logfn=None) -> bool:
    """`driven_by_a_test()` plus a line saying what was skipped.

    Say it out loud: a suppressed side effect nobody can see is how the NEXT
    outage gets mistaken for this guard doing its job."""
    if not driven_by_a_test():
        return False
    (logfn or print)(
        "  [live-effects] refusing to {} — a unit test is driving this call "
        "(automations.shared.live_effects)".format(what))
    return True
