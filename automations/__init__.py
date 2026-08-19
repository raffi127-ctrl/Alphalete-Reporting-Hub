"""Alphalete Reporting Hub automations.

This file exists ONLY to install the hand-run Hub auto-publish hook (Megan
2026-08-19), so a report run by hand from any machine still lights its card.
See automations/shared/hub_autopublish.py for the guards — it is DEFAULT OFF
(HUB_AUTOPUBLISH=1) and stays out of the way of any run the orchestrator or
mini_control owns.

Kept deliberately tiny and failure-proof: it registers an atexit callback and
nothing else. Importing `automations` must never get slower or riskier because
of this file, and a broken hook must never stop a report from importing.
"""
try:
    from automations.shared import hub_autopublish as _hub_autopublish
    _hub_autopublish.install()
except Exception:  # noqa: BLE001 — the package must import even if the hook can't
    pass
