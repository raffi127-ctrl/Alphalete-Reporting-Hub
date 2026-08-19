"""Make a HAND-RUN report publish its own Hub pill.

WHY (Megan 2026-08-19): a report run by hand really ran, but its Hub card stayed
white — only the orchestrator and the handful of self-publishing modules ever
call publish_done. That day owner_showdown, daily_rep_breakdown and the d2d
metrics all ran from Megan's laptop and every one of those cards read as
missing, which is what made "did it actually run?" unanswerable from the Hub.

HOW IT STAYS SAFE — it publishes ONLY when every one of these holds:

  * HUB_AUTOPUBLISH=1 is set (DEFAULT OFF — this touches every report's exit
    path, which is exactly the blast radius that broke the 4am batch on
    2026-08-19; it gets enabled after a dry-run batch, not on a hunch).
  * HUB_REPORT_ID is NOT set. Both day_orchestrator.run and mini_control export
    it for the reports they spawn, and both already publish — so that variable
    means "a runner above me owns this run" and we must stay out of the way or
    the card gets two rows.
  * the process is exiting CLEANLY (no live exception, exit status 0/None).
  * the entrypoint is a real `python -m automations.<pkg>...` run.
  * argv carries no --dry-run / --preview / --sandbox / --help — a rehearsal
    must never mark a card green.
  * the module maps to a Hub card that ALREADY exists (create=False), so a
    stray script can never invent one.

Everything is wrapped: a failure here can never affect the report's own exit.
"""
from __future__ import annotations

import os
import sys

_INSTALLED = False
_SKIP_ARGS = ("--dry-run", "--dryrun", "--preview", "--sandbox", "--help", "-h",
              "--make-sandbox", "--probe-only", "--simulate")


def enabled() -> bool:
    if os.environ.get("HUB_AUTOPUBLISH", "").strip() not in ("1", "on", "true"):
        return False
    # A runner above us owns (and publishes) this run.
    return not (os.environ.get("HUB_REPORT_ID") or "").strip()


def _report_id() -> str:
    """`python -m automations.foo.run` -> 'foo'. Empty when this isn't a report."""
    mod = getattr(sys.modules.get("__main__"), "__package__", "") or ""
    if not mod.startswith("automations."):
        return ""
    parts = mod.split(".")
    return parts[1] if len(parts) > 1 else ""


def _publish() -> None:
    try:
        if not enabled():
            return
        if any(a in _SKIP_ARGS for a in sys.argv[1:]):
            return
        if getattr(sys, "last_value", None) is not None:
            return                                  # died on an exception
        rid = _report_id()
        if not rid:
            return
        from automations.day_orchestrator import hub_coverage as hc
        card = hc.resolve_card(rid, create=False)   # never invent a card
        if not card:
            return
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(rid, rid, status="success")
    except Exception:                               # noqa: BLE001
        pass                                        # never touch the report's exit


def install() -> None:
    """Register the at-exit publish. Cheap and idempotent; does no work and
    imports nothing heavy unless the run actually qualifies at exit."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    try:
        import atexit
        atexit.register(_publish)
    except Exception:                               # noqa: BLE001
        pass
