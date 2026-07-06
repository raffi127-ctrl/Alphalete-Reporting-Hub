"""Publish a completed orchestrator run to the Hub's shared "Hub Activity" tab.

The Hub marks a card "ran today" by reading SUCCESS rows from this tab
(dashboard._hub_recent_runs → _was_run_successfully_today). Runs the mini does
on its own never reached the Hub because they only updated the orchestrator's
local day_state — a different machine, a different store (Megan 2026-06-25:
"if reports were ran, even by the mini, they should be marked as ran on the
Hub"). So when a report finishes DONE, we append the same shape of row the Hub
writes for a click-run.

This is WRITE-ONLY and one-sided: the Hub already reads the tab, no Hub change
needed. Best-effort — never raises into the orchestrator loop.

NOTE: the Hub keys on its CARD id, which differs from our schedule_config
report_id (underscores vs hyphens, sometimes a different name). _HUB_CARD maps
ours → theirs. A report with no Hub card (weather_alert) is a no-op.
"""
from __future__ import annotations

import datetime as dt
import socket
import uuid

from automations.recruiting_report import fill as _fill

# The Hub Activity tab lives on the intake/backlog workbook (matches
# dashboard.HUB_ACTIVITY_SHEET_ID / HUB_ACTIVITY_TAB).
HUB_ACTIVITY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
HUB_ACTIVITY_TAB = "Hub Activity"
# Column order must match dashboard.HUB_ACTIVITY_HEADERS exactly.
#   RunID, Started At, Report ID, Report Name, User, Machine, PID, Status, Ended At

# orchestrator report_id -> Hub CARD id. Reports absent here have no Hub card.
_HUB_CARD = {
    "att_focus_raf": "recruiting",
    "carlos_focus": "recruiting-carlos",
    "alphalete_org_focus": "recruiting-alphalete-org",
    "daily_focus": "daily-focus",
    "daily_rep_breakdown": "daily-rep-breakdown",
    "daily_metrics": "daily-metrics",
    "fiber_activations": "fiber-activations",
    "captainship_activations": "captainship-activations",
    "captainship_churn": "captainship-new-internet-wireless-churn",
    "owners_metrics_churn": "owners-metrics-churn",
    "recruiter_retention_daily": "daily-1st-round-recruiter-percent",
    "recruiter_retention_weekly": "ongoing-1st-round-recruiter-retention",
    "country_metrics": "country-metrics",
    "int_wow_penetration": "int-wow-penetration",
    "org_sales_board": "org-sales-board",
    "org_sales_board_email": "sales-board-screenshot-email",
    "leaders_call": "leaders-call",
    "residential_rep_count": "residential_rep_count",
    "rashad_metrics": "rashad-metrics",
    "frontier_opt": "frontier-opt-data-pull",
    "financial_report": "financial-pull",
    "brand_audit": "brand-health-audit",
    "alphalete_production": "alphalete-production",
    "tableau_screenshots": "tableau-screenshots",
    # weather_alert: Slack-only, no Hub card → not published.
}


def hub_card_id(report_id: str):
    """The Hub card id for an orchestrator report_id, or None."""
    return _HUB_CARD.get(report_id)


def _ws():
    return _fill._client().open_by_key(HUB_ACTIVITY_SHEET_ID).worksheet(HUB_ACTIVITY_TAB)


def publish_running(report_id: str, report_name: str):
    """Append a 'started' row so the Hub shows this mini run as RUNNING (yellow),
    live, from ANY machine's Hub — the dashboard already reads these rows
    (_hub_active_runs) with a 2h staleness guard. Returns the RunID to hand to
    publish_done (which flips this same row running->done in place), or None if the
    report has no Hub card / the write failed. Best-effort — never raises."""
    card = _HUB_CARD.get(report_id)
    if not card:
        return None
    run_id = uuid.uuid4().hex[:12]
    try:
        _ws().append_row(
            [run_id, dt.datetime.now().isoformat(timespec="seconds"), card,
             report_name, "Mini (auto)", socket.gethostname(), "", "started", ""],
            value_input_option="RAW")     # column shape matches dashboard.HUB_ACTIVITY_HEADERS
        return run_id
    except Exception:
        return None


def publish_done(report_id: str, report_name: str, status: str = "success",
                 run_id: str | None = None) -> bool:
    """Mark a run finished on the Hub. If `run_id` (from publish_running) is given,
    UPDATE that 'started' row in place (Status col 8 + Ended At col 9) so the card
    flips running->done and doesn't leave a dangling yellow pill. Otherwise append a
    fresh finished row (the reverify / no-prior-start path). Returns True if the Hub
    was touched, False if the report has no Hub card. Best-effort — never raises."""
    card = _HUB_CARD.get(report_id)
    if not card:
        return False
    now = dt.datetime.now().isoformat(timespec="seconds")
    try:
        ws = _ws()
        if run_id:
            cell = ws.find(str(run_id))
            if cell:
                ws.update_cell(cell.row, 8, status)                       # Status
                ws.update([[now]], f"I{cell.row}", value_input_option="RAW")  # Ended At
                return True
        ws.append_row(
            [uuid.uuid4().hex[:12], now, card, report_name, "Mini (auto)",
             socket.gethostname(), "", status, now],
            value_input_option="RAW")
        return True
    except Exception:
        return False
