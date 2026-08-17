"""Config for the Due Diligence per-rep report.

Every source URL, the Sheet target, and the request channel are env-overridable
so the report can point at a sandbox Sheet / test channel while building
(Eve's sandbox-first rule) without touching code.

Kept deliberately import-light: the heavy Tableau modules (opt_phase, which
pulls in patchright) are imported lazily in pull.py, so the formatter / Sheet
preview / watcher all import cleanly without a browser stack installed.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root: .../automations/due_diligence/config.py -> parents[2]
WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUT_DIR = WORKSPACE / "output" / "due_diligence"
STATE_PATH = OUTPUT_DIR / "watch_state.json"

# --- The Due Diligence log Sheet (one tab per ICD) --------------------------
# Megan's dedicated DD log (2026-07-28): a tab per ICD/owner; each requested rep
# is appended to their ICD's tab. Override DD_SHEET_ID with a sandbox copy while
# building. (Eve's original template — 1YgiiodwnIq… — is the layout reference.)
DD_SHEET_ID = os.environ.get("DD_SHEET_ID") or "1RB07z5xmXBzFgKPRmbvqsvbFJ4yymrsk2z0tkMeCbpQ"
# ICD tabs are matched by the owner name (from the Product Sales 'Owner Name'
# column). Set DD_TAB_OVERRIDE to force one tab title (testing only).
DD_TAB_OVERRIDE = os.environ.get("DD_TAB_OVERRIDE", "").strip()

# --- Slack: DM the bot ------------------------------------------------------
# Raf (and other leaders) DM the bot directly; it polls each allowed user's DM
# and answers in-thread. DD_DM_USERS is a comma-separated allowlist of who the
# bot serves — ids (U…/W…), emails, or names. REQUIRED before live (blank = the
# bot answers no one), so DD performance data only goes to named leaders.
# [[feedback_verify_slack_recipient]]
DD_DM_USERS = [u.strip() for u in os.environ.get("DD_DM_USERS", "").split(",") if u.strip()]

# --- Window --------------------------------------------------------------
WEEKS = int(os.environ.get("DD_WEEKS", "8"))
RECENT_WEEKS = int(os.environ.get("DD_RECENT_WEEKS", "4"))   # the "4 Week Average"

# --- Tableau source overrides (env only) ------------------------------------
# Defaults resolve lazily in pull.py from the modules that MAINTAIN these views
# (opt_phase = product sales / metrics; office_metrics.offices = all-team churn),
# so we never drift. Set any of these to point a source elsewhere for testing.
PRODUCT_VIEW_URL = os.environ.get("DD_PRODUCT_VIEW_URL", "")
PRODUCT_SHEET = os.environ.get("DD_PRODUCT_SHEET", "")
CHURN_NI_VIEW_URL = os.environ.get("DD_CHURN_NI_VIEW_URL", "")
CHURN_WL_VIEW_URL = os.environ.get("DD_CHURN_WL_VIEW_URL", "")
CHURN_NI_SHEET = os.environ.get("DD_CHURN_NI_SHEET", "ICD Churn")
CHURN_WL_SHEET = os.environ.get("DD_CHURN_WL_SHEET", "ICD Churn (Wireless)")
METRICS_NI_URL = os.environ.get("DD_METRICS_NI_URL", "")
METRICS_NI_SHEET = os.environ.get("DD_METRICS_NI_SHEET", "")
METRICS_WL_URL = os.environ.get("DD_METRICS_WL_URL", "")
METRICS_WL_SHEET = os.environ.get("DD_METRICS_WL_SHEET", "")

# Product-type strings the DailyRepBDreportpull crosstab emits: 'NEW INTERNET',
# 'UPGRADE INTERNET', 'VIDEO', 'WIRELESS'. "New INT Sales" = NEW INTERNET only,
# so match 'new internet' (NOT bare 'internet', which would also grab UPGRADE
# INTERNET). Matched as a lowercase substring so a label tweak still works.
NI_PRODUCT_MATCH = "new internet"
WL_PRODUCT_MATCH = "wireless"

# Metrics crosstab field names (exact, from opt_phase.METRICS_SCRAPED). The
# 30-60 cancel rate is derived as 100 - activation, the same as the office
# metrics report + Eve's manual math.
METRIC_NI_CANCEL_0_30 = "0-30 day New Internet cancel rate"
METRIC_NI_ACT_30_60 = "30-60 day New Internet activation rate"
METRIC_WL_CANCEL_0_30 = "0-30 day wireless cancel rate"
METRIC_WL_ACT_30_60 = "30-60 Activation Rate"

# Slack reactions the watcher uses to mark a request in-progress / done.
DONE_REACTION = os.environ.get("DD_DONE_REACTION", "white_check_mark")
WORKING_REACTION = os.environ.get("DD_WORKING_REACTION", "hourglass_flowing_sand")


# --- Lazy default resolvers (import heavy modules only when actually pulling) -
def _bare_view(url: str) -> str:
    """Strip any query string off a view URL.

    The product view is the ONE source we week-filter: opt_phase._week_url()
    appends the week filter with a literal '?', so a URL that already carries a
    query (Tableau's UI copies them with '?:iid=1') produces a second '?' and
    Tableau silently drops the filter — every week then returns the SAME
    unfiltered crosstab, which is what made the weekly sales columns go flat.
    Paste-from-browser URLs are the norm, so sanitize instead of trusting them.
    """
    return (url or "").split("?", 1)[0]


def product_source() -> tuple:
    from automations.recruiting_report.opt_phase import PRODUCT_SALES_SHEET
    # DDfullyEXP (Megan 2026-07-28): fully rep-expanded, NO rep/owner filter, so
    # every rep is included. The old DailyRepBDreportpull custom view had a saved
    # filter that dropped reps (e.g. Corrieonna Johnson, Aden Berhane's newer team).
    default = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
               "e594b76d-504f-4868-8c4a-ec18893bebb8/DDfullyEXP")
    return (_bare_view(PRODUCT_VIEW_URL or default), PRODUCT_SHEET or PRODUCT_SALES_SHEET)


def metrics_ni_source() -> tuple:
    # MetricsINTfullyEXP (Eve 2026-08-17): the Internet twin of MetricsfullyEXP,
    # expanded to individual Rep Name. The BASE Metrics view is collapsed to ICD
    # (88 rows, no 'Rep Name'), so from ~WE 8.09 every rep's 0-30 / 30-60 New INT
    # cancel came back blank — silently, because _slice_team swallows the miss.
    # Expanding by hand is not automatable: the '+' on the header lives in a
    # canvas inside the viz iframe, and the exporter re-navigates on every call.
    # [[project_metrics-internet-needs-expanded-custom-view]]
    from automations.recruiting_report.opt_phase import METRICS_SHEET
    default = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "ATTTRACKER2_1-D2D/Metrics/"
               "de2c904b-1438-4d76-bb14-8e5b2861d2ec/MetricsINTfullyEXP")
    return (METRICS_NI_URL or default, METRICS_NI_SHEET or METRICS_SHEET)


def metrics_wl_source() -> tuple:
    # MetricsfullyEXP (Megan 2026-07-28): the ONLY wireless metrics view broken
    # out to individual Rep Name — the office/AP-WIRELESSMETRICS one stops at the
    # sub-owner level, so it can't give per-rep wireless cancel. Verified against
    # the VA's manual pull (Baraquiel/Emilio/Iliya exact).
    default = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "ATTTRACKER2_1-D2D/Metrics/"
               "e89dd6ab-9c67-464e-b414-3012723ba607/MetricsfullyEXP?:iid=1")
    return (METRICS_WL_URL or default,
            METRICS_WL_SHEET or "Metrics Call Last week data (Wireless)")


def churn_ni_source() -> tuple:
    from automations.office_metrics.offices import ALL_OFFICE_CHURN_NI
    return (CHURN_NI_VIEW_URL or ALL_OFFICE_CHURN_NI, CHURN_NI_SHEET)


def churn_wl_source() -> tuple:
    from automations.office_metrics.offices import ALL_OFFICE_CHURN_WL
    return (CHURN_WL_VIEW_URL or ALL_OFFICE_CHURN_WL, CHURN_WL_SHEET)
