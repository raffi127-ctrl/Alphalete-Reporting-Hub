"""Every id, path and channel this report touches, in one place."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path.home() / ".config" / "recruiting-report"

# --- SaraPlus (CARLOS's login, not the sales board's) -------------------------
LOGIN_URL = "https://ui.saraplus.com"

# ITS OWN FILE. alphalete_sales_board reads saraplus-creds.json
# (alphaletemarketing@gmail.com) and that login is NOT this report's -- Megan
# 2026-09-02: "make sure you're ONLY using Carlos' sara plus login to access".
# Two files means a password change on one account can never quietly hand this
# report the other dealer's orders.
#   lucy push_cred_file saraplus-creds-b2b "Lucy 2" --machine "<box that has it>"
# File shape: {"email": "carhi1816@gmail.com", "password": "..."}
CREDS_PATH = CONFIG_DIR / "saraplus-creds-b2b.json"

# Its own Chrome profile too, for the same reason plus the collision guard:
# the sales-board sweep opens .saraplus_profile every 5 minutes on Lucy 1, and
# a shared profile is how one report adopts another's browser.
# [[reference_chrome_collision_guard]]
PROFILE_DIR = REPO_ROOT / "automations" / "uploaded" / ".saraplus_b2b_profile"

HUB_PATH = "Reports/ReportingHub.aspx"

# Tabs are clicked BY LABEL (Telerik RadTabStrip renders them as divs with no
# stable id), and the grid is found by its HEADER ROW, not by index -- the
# report's columns are read off the header every run.
TAB_DETAIL_REPORTS = "Detail Reports"
TAB_SALES_ORDER_HISTORY = "Sales Order History"
CUSTOMER_TYPE_BOTH = "Both"

# Header labels as the grid writes them. Anything missing here is a loud error,
# never a silent index shift.
COL_REP = "User Name"
COL_BUSINESS = "Business Name"
COL_ORDER_ID = "Order ID"
COL_ORDER_DATE = "Order Date"
REQUIRED_COLUMNS = [COL_ORDER_ID, COL_ORDER_DATE, COL_REP, COL_BUSINESS]

# On the View Customer page, the label that sits beside the number we want.
PRIMARY_PHONE_LABEL = "Primary Phone"

GRID_TIMEOUT_MS = 90_000
NAV_TIMEOUT_MS = 60_000

# --- RingCentral (Carlos's 'Alphalete Specialized Marketing' account) ---------
# NOT the rc_autoread account. See the module docstring.
# File shape -- ONE user, both jobs:
#   {"client_id": "...", "client_secret": "...", "jwt": "..."}
RC_CREDS_PATH = CONFIG_DIR / "ringcentral-b2b-creds.json"
RC_BASE_URL = "https://platform.ringcentral.com"

# WE SIGN IN AS TAYLOR (Megan 2026-09-02: "the ring central account we're using
# is with this email taylormkmiller7@gmail.com"). That is one identity doing
# both jobs, and it is the simpler shape by some distance:
#   * the contacts land in the address book of the line that actually texts
#     these customers, so a reply comes in with a name on it instead of an
#     unknown number;
#   * her message store is the one we read, and a RingCentral JWT authenticates
#     ONE user -- signing in as Carlos would have meant a second JWT minted on
#     Taylor just to read her texts.
# Both calls therefore address extension '~' (whoever the token is), never a
# hardcoded id: an extension number is a thing that gets reassigned.
RC_LOGIN_EMAIL = "taylormkmiller7@gmail.com"
CONTACTS_OWNER_NAME = "Taylor Miller"      # ext 134 -- and the watched line
WATCH_OWNER_NAME = "Taylor Miller"
SELF_EXTENSION = "~"

# The label RingCentral puts on the phone number of a created contact.
PHONE_LABEL = "mobile"

# --- Slack --------------------------------------------------------------------
# Carlos: "have Lucy send the message on the A players and the B2B chat, and it
# can send it in the metrics thread." Both of his channels, same as
# b2b_dispositions posts to.
CHANNELS = ["C0AJQA8P716", "C07J46MQNUX"]
CHANNEL_LABEL = {
    "C0AJQA8P716": "#a-players-b2b",
    "C07J46MQNUX": "#alphalete-gp-sales",
}

SLACK_HEADER = ":telephone_receiver: *No Text Sent To Customer*"

# --- state --------------------------------------------------------------------
# Order ids already turned into a contact. Creating a RingCentral contact is
# not undoable from here, so the guard is written the moment each contact
# lands, not at the end of the run.
STATE_PATH = CONFIG_DIR / "rc_contact_sync_state.json"


def creds() -> Dict[str, str]:
    """Carlos's SaraPlus {'email','password'}, or an error naming the fix."""
    env_user = os.environ.get("SARA_PLUS_B2B_EMAIL")
    env_pass = os.environ.get("SARA_PLUS_B2B_PASSWORD")
    if env_user and env_pass:
        return {"email": env_user, "password": env_pass}
    if not CREDS_PATH.exists():
        raise RuntimeError(
            "no B2B SaraPlus credentials at %s. This report must run on "
            "CARLOS's SaraPlus login (carhi1816@gmail.com) -- the sales "
            "board's saraplus-creds.json is a different dealer and is "
            "deliberately not used here. Push them with `lucy push_cred_file "
            "saraplus-creds-b2b \"Lucy 2\" --machine \"<box that has them>\"`, "
            "or export SARA_PLUS_B2B_EMAIL / SARA_PLUS_B2B_PASSWORD."
            % CREDS_PATH)
    data = json.loads(CREDS_PATH.read_text())
    missing = [k for k in ("email", "password") if not data.get(k)]
    if missing:
        raise RuntimeError("%s is missing %s" % (CREDS_PATH, ", ".join(missing)))
    return {"email": data["email"], "password": data["password"]}


def rc_creds() -> Dict[str, str]:
    """RingCentral app credentials for CARLOS's account."""
    if not RC_CREDS_PATH.exists():
        raise RuntimeError(
            "no RingCentral credentials at %s. They are NOT the ones baked "
            "into automations/rc_autoread/run.py -- that app belongs to the "
            "other RingCentral account (Dylan/HR, main +1 207-464-7960) and "
            "Taylor Miller has no extension in it. Carlos's account "
            "('Alphalete Specialized Marketing') needs its own app + JWT."
            % RC_CREDS_PATH)
    data = json.loads(RC_CREDS_PATH.read_text())
    missing = [k for k in ("client_id", "client_secret", "jwt")
               if not data.get(k)]
    if missing:
        raise RuntimeError("%s is missing %s" % (RC_CREDS_PATH, ", ".join(missing)))
    # Both default to the signed-in user. They are overridable only so a future
    # split (contacts in one book, texts on another line) doesn't need a code
    # change -- normally neither is set.
    data.setdefault("contacts_extension_id", SELF_EXTENSION)
    data.setdefault("watch_extension_id", SELF_EXTENSION)
    data.setdefault("expected_email", RC_LOGIN_EMAIL)
    return data


def load_state() -> Dict[str, dict]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except (ValueError, OSError):
        return {}


def save_state(state: Dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(STATE_PATH)


def prune_state(state: Dict[str, dict], keep_days: int = 120) -> Dict[str, dict]:
    """Drop entries older than keep_days so the guard file stays small. The
    window is generous on purpose -- a short one would let an old order be
    re-contacted if the report is ever re-run over a back date."""
    cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    return {k: v for k, v in state.items()
            if str(v.get("day", "")) >= cutoff}


def yesterday(now: Optional[dt.datetime] = None) -> dt.date:
    return (now or dt.datetime.now()).date() - dt.timedelta(days=1)
