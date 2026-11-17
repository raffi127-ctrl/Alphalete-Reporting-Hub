"""Settings for the cancel/disconnect feedback outreach.

RingCentral creds live in their OWN file (cancel-feedback-rc-creds.json), a
SEPARATE credential from the wrap-up auto-read JWT: that one signs in as the
"HR Department" user (can read Dylan's line but can't send from his number),
while this one signs in as the "Dylan Twaddle" user (ext 108) that OWNS
214-845-6450, so sends go out same-extension. Don't merge the two.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict

CONFIG_DIR = Path.home() / ".config" / "recruiting-report"

# --- RingCentral (dedicated Dylan-user JWT; see module docstring) ------------
RC_BASE_URL = "https://platform.ringcentral.com"
RC_CREDS_PATH = CONFIG_DIR / "cancel-feedback-rc-creds.json"


def rc_creds() -> Dict[str, str]:
    """client_id/client_secret/jwt + send_from/send_extension_id/
    expected_owner_id, read from the dedicated creds file."""
    return json.loads(RC_CREDS_PATH.read_text(encoding="utf-8-sig"))


# --- Message -----------------------------------------------------------------
# Dylan's wording (2026-11-17). One template for both cancels and disconnects.
# No opt-out line by Dylan's choice; STOP is still auto-honored on the backend.
MESSAGE_TEMPLATE = (
    "Hi {first}, this is Dylan reaching out about the AT&T order you placed "
    "with the local Door to Door reps — we saw your internet order didn't "
    "end up going as planned. We'd really value your honest written feedback: "
    "what was the main reason it didn't work out for you? It genuinely helps "
    "us do better. Thanks for taking a second to reply - I'll pass this "
    "feedback along to the local office for coaching!"
)


def render(first: str) -> str:
    return MESSAGE_TEMPLATE.format(first=(first or "there").strip() or "there")


# --- Compliance / sending guards ---------------------------------------------
# Only send during local daytime (TCPA quiet hours are 8am-9pm). Hours are the
# recipient-local clock; we approximate with the account's local time.
QUIET_HOURS = (8, 21)          # [start, end) in 24h local time
ONE_TEXT_PER_CUSTOMER = True   # never text the same number twice, ever
STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit",
              "optout", "opt-out", "revoke"}

# --- Log (dedicated Google Sheet; Outreach + Responses tabs) -----------------
# Filled in once the sandbox sheet is created. Empty => no sheet wired yet, so
# live sends are refused and dry-run just prints what it WOULD log.
LOG_SHEET_ID = ""
OUTREACH_TAB = "Outreach"
RESPONSES_TAB = "Responses"
OUTREACH_HEADERS = ["Texted At", "Customer", "Phone", "Kind", "Reason", "Rep",
                    "Owner", "Status", "Message ID"]
RESPONSES_HEADERS = ["Received At", "Phone", "Customer", "Feedback", "Opted Out",
                     "Message ID"]

# --- Source window -----------------------------------------------------------
# Status Date == the target day (yesterday). The crosstab URL still pulls a wide
# Order-Date window so a status change on an older order is caught.
ORDER_WINDOW_DAYS = 40


def yesterday(now: dt.datetime | None = None) -> dt.date:
    return (now or dt.datetime.now()).date() - dt.timedelta(days=1)


# Office scope. Preview on Rafael Hidalgo's OWN office first (Dylan 2026-11-17),
# then roll out to his whole captainship. "full" = RAF_OWNERS (both source
# modules'); Starr/Sahil are a different captainship and are intentionally out.
TEST_OWNERS = {"Rafael Hidalgo"}


def captainship_owners() -> set:
    """Every office in Rafael Hidalgo's captainship (union of both source
    modules' RAF_OWNERS, in case one adds an office before the other)."""
    from automations.canceled_orders import run as cr
    from automations.disconnects import run as dr
    return set(cr.RAF_OWNERS) | set(dr.RAF_OWNERS)


def owners_for_scope(scope: str) -> set:
    """'test' => Rafael's office only; 'full' => the whole captainship."""
    return set(TEST_OWNERS) if scope == "test" else captainship_owners()
