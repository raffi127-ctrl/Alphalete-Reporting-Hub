"""NDS T&C check: every id, label and destination in one place."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "nds_tnc_check"

# The NDS dealer (alphaletegp) -- same creds file nds_metrics reads. OWN
# Chrome profile, under automations/uploaded so chrome_guard covers it: the
# 7:30am run can overlap nds_metrics' own pull, and two Chromes on one
# persistent profile is "profile in use", not a report.
NDS_SARA_CREDS = (Path.home() / ".config" / "recruiting-report"
                  / "saraplus-creds-nds.json")
PROFILE_DIR = REPO_ROOT / "automations" / "uploaded" / ".saraplus_nds_tnc_profile"

# --- the View Customer card -------------------------------------------------
# Read off Carlos's screenshot 2026-11-05 (alphaletegp, Sales Order History,
# View Customer): the block reads
#   T&C Sent Date: 11/4/2026 6:57:00 PM
#   Confirmation Status: Confirmed via API Automatic
#   T&C Sent Via: Email to <address>
#   Confirmation Date: 11/4/2026 6:58:30 PM
#   Notes: ...
# Carlos: "make sure that there's a confirmation date filled out, not that
# there's just some form of sent status ... There's got to be a date there."
# Every label on the card that can FOLLOW one of ours bounds its value.
CARD_LABELS = [
    "Current Status:", "FPV Complete Date:", "Billing Preference:",
    "T&C Sent Date:", "Confirmation Status:", "T&C Sent Via:",
    "Confirmation Date:", "Notes:",
]
# Not fields, but they sit right after Confirmation Date on the live card
# (probe 2026-11-05: '... 6:23:24 PM Order Summary Notes:'), so they bound
# the value too.
STOP_LABELS = ["Order Summary", "Order History"]
LABEL_SENT_VIA = "T&C Sent Via:"
LABEL_CONFIRMED = "Confirmation Date:"

# Grid columns, by LABEL (never by index). Candidates in preference order --
# the NDS dealer's grid is the same Telerik RadGrid as the b2b dealer's, but
# the header spelling is checked at run time and logged.
COL_ORDER_ID = ["Order ID", "Order Id", "DSI #", "Order #"]
COL_REP = ["User Name", "Sales Rep", "Rep Name"]
COL_SALESPERSON = ["Salesperson"]       # logged beside User Name (optional)
COL_CUSTOMER = ["Customer Name", "Customer", "Name"]

# --- Slack ------------------------------------------------------------------
# #alphalete-gp-sales, where the NDS Metrics thread lives (Carlos 2026-11-05:
# "whenever you're doing the NDS metrics thread"). Posts go under the day's
# NDS Metrics thread when nds_metrics has opened it, else top-level.
CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")
# Slack user IDs, never names (8 Nicos, 11 Sebastians in this workspace).
# Both confirmed in b2b_dispositions.config (Megan 2026-08-06).
MENTIONS = [
    "U046G04P5LG",   # Carlos Hidalgo
    "U05LLCCSB2Q",   # Sebastian Avellaneda
]

# Carlos's wording: 'send a Slack message tagging Sebastian and me, saying
# "Hey customer," and then give us the first name ... and then give us the
# sales rep's name. TNC has not been completed.'
def message(customer_first: str, rep: str) -> str:
    tags = " ".join("<@%s>" % u for u in MENTIONS)
    return ("%s Hey, customer %s (rep: %s) — TNC has not been completed."
            % (tags, _title(customer_first) or "(no name)",
               _title(rep) or "(no rep)"))


def _title(s: str) -> str:
    """SaraPlus shouts names (ALBA ALVAREZ) -- the post says Alba Alvarez."""
    return " ".join(w[:1].upper() + w[1:].lower() for w in (s or "").split())

STATE_PATH = OUT_DIR / "posted.json"   # {"YYYY-MM-DD|slot": [order ids]}
NAV_TIMEOUT_MS = 60_000
CARD_TIMEOUT_MS = 25_000
MAX_PAGES = 10
