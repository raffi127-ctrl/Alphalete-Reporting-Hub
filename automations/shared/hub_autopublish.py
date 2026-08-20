"""Make a HAND-RUN report publish its own Hub pill.

WHY (Megan 2026-08-19): a report run by hand really ran, but its Hub card stayed
white — only the orchestrator and the handful of self-publishing modules ever
call publish_done. That day owner_showdown, daily_rep_breakdown and the d2d
metrics all ran from Megan's laptop and every one of those cards read as
missing, which is what made "did it actually run?" unanswerable from the Hub.

WHY NOT atexit (2026-08-19, second pass): the first version registered an
atexit callback and treated `sys.last_value is None` as "exited cleanly". It
does not mean that. Measured on this repo's Python:

    sys.exit(1)                          -> sys.last_value is None
    raise SystemExit("no header in row") -> sys.last_value is None
    an unhandled RuntimeError            -> sys.last_value is set

Only the traceback case is caught, and it is the RAREST of the three: 74 of the
90 run.py modules end in `sys.exit(main())`, so a FAILED hand-run would have
published SUCCESS and painted the card green. That is worse than the white card
it replaced — a white card sends you to look, a green one tells you not to.
CPython handles SystemExit before sys.excepthook and before sys.last_* are set,
and atexit cannot see the exit status at all, so no atexit-shaped hook can get
this right.

So we wrap the runpy call that executes the module instead: it is the one place
that sees the module's real ending — a clean return, a SystemExit and its code,
or a live exception. The private-API use is deliberate and fully guarded; if
runpy ever changes shape, install() no-ops and every report behaves exactly as
it does today.

HOW IT STAYS SAFE — it publishes ONLY when every one of these holds:

  * HUB_AUTOPUBLISH=1 is set (DEFAULT OFF — this touches every report's exit
    path, which is exactly the blast radius that broke the 4am batch on
    2026-08-19; it gets enabled after a dry-run batch, not on a hunch).
  * HUB_REPORT_ID is NOT set. Both day_orchestrator.run and mini_control export
    it for the reports they spawn, and both already publish — so that variable
    means "a runner above me owns this run" and we must stay out of the way or
    the card gets two rows.
  * nothing in the process already published for this run — the ~12 modules
    that call hub_activity.log_completed / publish_done themselves mark it, so
    a second row can't fill a daily_runs>1 pill off a single pass.
  * the entrypoint is a real `python -m automations.<pkg>.run` run.
  * argv carries no --dry-run / --preview / --sandbox / --help — a rehearsal
    must never mark a card green.
  * the module maps to a Hub card that ALREADY exists (create=False), so a
    stray script can never invent one.

A FAILED hand-run publishes 'failed' and does NOT open a Slack incident
(alert_on_fail=False) — the person is sitting there watching it fail. A
SUCCESSFUL hand-run still closes an incident thread the last failure opened,
which is how most of these actually get fixed.

Everything is wrapped: a failure here can never affect the report's own exit.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

_INSTALLED = False
_REPORTED = False       # a module already published for this run
_FIRED = False          # we already published (never twice in one process)

_SKIP_ARGS = ("--dry-run", "--dryrun", "--preview", "--sandbox", "--help", "-h",
              "--make-sandbox", "--probe-only", "--simulate", "--test", "--audit",
              # LOOKING is not RUNNING. These print what's there and exit —
              # sci_campaigns --list ("list the tracker weeks … then exit"),
              # new_owners --status ("print the bank and the log"),
              # icd_sales_board --check. Publishing one would tell Megan the
              # report ran today when nobody did any work.
              "--list", "--status", "--check")

# Runs FROM a .run module that must never colour a card of their own: the
# orchestrator is the thing publishing everyone else's rows.
_INFRA = {"day_orchestrator"}

_CONFIG = (Path(__file__).resolve().parents[2] / "automations" /
           "day_orchestrator" / "schedule_config.json")


def enabled() -> bool:
    if os.environ.get("HUB_AUTOPUBLISH", "").strip() not in ("1", "on", "true"):
        return False
    # A runner above us owns (and publishes) this run.
    return not (os.environ.get("HUB_REPORT_ID") or "").strip()


def mark_reported() -> None:
    """Called by hub_activity.log_completed and hub_publish.publish_done so a
    module that already told the Hub about itself keeps this hook silent."""
    global _REPORTED
    _REPORTED = True


def already_reported() -> bool:
    return _REPORTED


def _code_ok(code) -> bool:
    """A SystemExit payload is success only for None / 0. A STRING payload is an
    error message — `raise SystemExit("no '#' header in row 3")` exits 1."""
    return code is None or code == 0


def _resolve(module_name: str) -> Optional[Tuple[str, str, str]]:
    """(report_id, display_name, card_id) for `automations.<pkg>.run`, or None.

    Resolves through schedule_config's `command` FIRST, because the folder name
    is not the report id: automations.recruiting_report.run is `att_focus_raf`
    on card `recruiting`, and matching on the folder alone leaves the Hub's
    primary card unlit. Falls back to the folder name for the modules that
    aren't on the scheduler.

    One module can serve several reports, and then `base_args` is what tells
    them apart — automations.tableau_screenshots.run is the trackers card on
    `--text-trackers` and the BOX card on `--late-only --text-trackers`. We keep
    the entries whose base_args all appear in argv and take the most specific
    one, so the box run lights the box card instead of its neighbour. A tie
    across two different cards stays unresolved: no pill beats the wrong pill.
    """
    try:
        from automations.day_orchestrator import hub_coverage as hc
    except Exception:
        return None

    pkg = module_name.split(".")[1] if module_name.count(".") >= 2 else ""
    if pkg in _INFRA:
        return None

    try:
        reports = json.loads(_CONFIG.read_text(encoding="utf-8"))["reports"]
    except Exception:
        reports = {}

    argv = set(sys.argv[1:])
    best: list = []
    best_score = -1
    for rid, r in reports.items():
        if rid in _INFRA or (r.get("command") or [None])[0] != module_name:
            continue
        base = list(r.get("base_args") or [])
        if not set(base) <= argv:
            continue                                # this run isn't that report
        card = hc.resolve_card(rid, create=False)    # never invent a card
        if not card:
            continue
        hit = (rid, r.get("display_name") or rid, card)
        if len(base) > best_score:
            best_score, best = len(base), [hit]
        elif len(base) == best_score:
            best.append(hit)
    cards = {h[2] for h in best}
    if len(cards) == 1:
        return best[0]
    if cards:
        return None                                 # >1 card = ambiguous, skip

    card = hc.resolve_card(pkg, create=False) if pkg else None
    return (pkg, pkg, card) if card else None


def _status_with_manifest(status: str, report_id: str, card: str) -> str:
    """Upgrade a clean exit to 'partial' when the run's own manifest says parts
    failed — org_sales_board and friends exit 0 on an INCOMPLETE pass on
    purpose (a non-zero exit would read as FAILED before verify runs), and a
    green pill would bury it."""
    if status != "success":
        return status
    try:
        from automations.shared import run_manifest
        for key in (card, report_id):           # manifests are named either way
            out = run_manifest.outcome(key)
            if out in ("partial", "failed"):
                return out
    except Exception:
        pass
    return status


def _who() -> str:
    for var in ("USER", "USERNAME", "LOGNAME"):
        who = os.environ.get(var)
        if who:
            return "%s (hand-run)" % who
    return "hand-run"


def _publish(status: str, run_globals: dict) -> None:
    global _FIRED
    if _FIRED or _REPORTED or not enabled():
        return
    if any(a in _SKIP_ARGS for a in sys.argv[1:]):
        return
    name = getattr(run_globals.get("__spec__"), "name", None)
    if not name or not name.startswith("automations.") or not name.endswith(".run"):
        return
    hit = _resolve(name)
    if not hit:
        return
    report_id, display_name, card = hit
    status = _status_with_manifest(status, report_id, card)
    _FIRED = True
    try:
        from automations.day_orchestrator import hub_publish
        ok = hub_publish.publish_done(report_id, display_name, status=status,
                                      alert_on_fail=False, user=_who())
    except Exception:                               # noqa: BLE001
        ok = False
    if ok:
        print("[hub] card '%s' marked %s (hand-run). "
              "HUB_AUTOPUBLISH=0 turns this off." % (card, status), flush=True)


def install() -> None:
    """Wrap runpy's module executor so a hand-run publishes its own Hub row with
    the run's REAL outcome. Cheap and idempotent; imports nothing heavy unless
    the run actually qualifies at exit, and never raises."""
    global _INSTALLED
    if _INSTALLED or not enabled():
        return
    _INSTALLED = True
    try:
        import runpy
        orig = getattr(runpy, "_run_code", None)
        if orig is None or getattr(orig, "_hub_wrapped", False):
            return

        def _wrapped(code, run_globals, *a, **kw):
            # Only the top-level module counts: a nested runpy.run_module inside
            # a report is not the report finishing.
            top = run_globals.get("__name__") == "__main__"
            status = "success"
            try:
                return orig(code, run_globals, *a, **kw)
            except SystemExit as exc:
                status = "success" if _code_ok(exc.code) else "failed"
                raise
            except BaseException:
                status = "failed"
                raise
            finally:
                if top:
                    try:
                        _publish(status, run_globals)
                    except Exception:               # noqa: BLE001
                        pass    # reporting must never touch the report's exit

        _wrapped._hub_wrapped = True
        runpy._run_code = _wrapped
    except Exception:                               # noqa: BLE001
        pass
