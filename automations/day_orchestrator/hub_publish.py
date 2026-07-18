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
    # Raf's local office — folded onto the shared card with the other offices
    # (Megan 2026-07-16); it just still runs its own older module.
    "daily_metrics": "office-metrics",
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
    "board_compare": "org-sales-board-compare",
    "leaders_call": "leaders-call",
    "residential_rep_count": "residential_rep_count",
    # Sara+ issue escalation. This one runs every 5 min around the clock, so it
    # publishes ONLY when it actually escalates an issue (not on every tick) —
    # 288 heartbeat rows/day would bury the activity log. A quiet card here means
    # "no Sara+ issues reported", which is the normal, healthy state.
    "sara_down": "sara-plus-issues",
    # Every per-office metrics feed publishes to the ONE consolidated card
    # (dashboard._office_metrics_card) — same as the Tableau trackers. The card's
    # per-office ✅/❌ checklist carries which office missed; the pill is the
    # batch-level light. Adding an office = a row in office_metrics/offices.py
    # + its orchestrator entry + one line here.
    "rashad_metrics": "office-metrics",
    "aya_metrics": "office-metrics",
    "cyrus_metrics": "office-metrics",
    "hammad_metrics": "office-metrics",
    "kash_metrics": "office-metrics",
    "salik_metrics": "office-metrics",
    "cody_metrics": "office-metrics",
    "frontier_opt": "frontier-opt-data-pull",
    "financial_report": "financial-pull",
    "brand_audit": "brand-health-audit",
    "social_inbox": "social-media-posting",
    "alphalete_production": "alphalete-production",
    "tableau_screenshots": "tableau-screenshots",
    # The ~7am Box catch-up is its own card: it runs hours after the morning
    # trackers, so folding it into that card would leave one pill standing for two
    # runs that succeed or fail independently.
    "tableau_screenshots_box": "tableau-screenshots-box",
    "weather_alert": "lucy-weather-forecast",
    # Library reports run on their own LaunchAgent/rerun (not the 4am batch) and
    # mark themselves via run_library_report / their wrapper. Their Hub card id IS
    # the library id, so map it to itself so _cal_status matches (card goes green).
    "june_texas_de_brazil_monthly_competition": "june_texas_de_brazil_monthly_competition",
    # Weekly captainship reports: standalone LaunchAgents (Lucy 2 Mon/Tue, mini Tue)
    # that call publish_done from their wrapper. They ran fine for weeks but their
    # cards never went green — they were simply missing from this map, so Megan had
    # no way to tell a successful run from a silent miss (2026-07-14).
    "carlos_captainship_bonus": "carlos-captainship-bonus",
    "carlos_captainship_headcount": "carlos-captainship-headcount",
    "raf_captainship_bonus": "raf-captainship-bonus",
    # STF Field Check: standalone 11pm LaunchAgent on the mini that calls
    # publish_done from deploy/stf_field_check_11pm.sh — map so the card pill
    # reflects the real run (else it stays grey like the captainship bonuses did).
    "stf_field_check": "stf-field-check",
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


def publish_heartbeat(run_id: str) -> bool:
    """Re-stamp an open 'started' row's Started At (col 2) to now so its yellow
    pill stays LIVE past the Hub's 2h staleness window (dashboard.HUB_STALE_AFTER)
    — for a report the orchestrator is still working hours later (e.g. a board
    waiting on its not_before, or a Tableau report retrying while data lands).
    Only touches a row we opened (matched by RunID) and never its Status/Ended At.
    Best-effort — never raises. Returns True if a row was re-stamped."""
    if not run_id:
        return False
    now = dt.datetime.now().isoformat(timespec="seconds")
    try:
        ws = _ws()
        cell = ws.find(str(run_id))
        if not cell:
            return False
        ws.update([[now]], f"B{cell.row}", value_input_option="RAW")   # Started At
        return True
    except Exception:
        return False


def final_status(report_id: str, ok: bool) -> str:
    """The status to close a run's pill with: 'success' | 'partial' | 'failed'.

    A report that fans out to many parts (the Tableau trackers post to 5 Slack
    channels) can land MOST of them and miss one. Closing that red is wrong — a
    red pill on a report that mostly worked teaches people to ignore red. If the
    report wrote a manifest saying some parts succeeded and some failed, this
    returns 'partial' (the Hub colours it orange). Reports that don't record
    `succeeded` are unaffected: they still resolve to plain success/failed."""
    if ok:
        return "success"
    try:
        from automations.shared import run_manifest
        return run_manifest.outcome(report_id) or "failed"
    except Exception:      # noqa: BLE001 — status must never break the run
        return "failed"


def incomplete_status(report_id: str) -> str:
    """Pill status for a run the orchestrator marked INCOMPLETE (it RAN, with a
    note). Historically these show green ('ran') — keep that, EXCEPT upgrade to
    'partial' (orange) when the report's manifest explicitly records some parts
    succeeded and some failed (e.g. metrics posted to 6 of 8 channels). Reports
    that don't record `succeeded` are unchanged (still green)."""
    try:
        from automations.shared import run_manifest
        return "partial" if run_manifest.outcome(report_id) == "partial" else "success"
    except Exception:      # noqa: BLE001 — status must never break the run
        return "success"


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
