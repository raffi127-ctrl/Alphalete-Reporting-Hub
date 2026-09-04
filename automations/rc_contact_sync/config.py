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
#   python -m automations.rc_contact_sync.set_credentials --push "Lucy 2"
# (hidden prompt, mode 600, redacted transit -- the password never reaches
# shell history, a log or the Mini Control sheet), or move an existing copy:
#   lucy push_cred_file saraplus-creds-b2b "Lucy 2" --machine "<box that has it>"
# File shape: {"email": "carhi1816@gmail.com", "password": "..."}
CREDS_PATH = CONFIG_DIR / "saraplus-creds-b2b.json"

# Its own Chrome profile too, for the same reason plus the collision guard:
# the sales-board sweep opens .saraplus_profile every 5 minutes on Lucy 1, and
# a shared profile is how one report adopts another's browser.
# [[reference_chrome_collision_guard]]
PROFILE_DIR = REPO_ROOT / "automations" / "uploaded" / ".saraplus_b2b_profile"

# --- the login verification code ---------------------------------------------
# SaraPlus emails a code on login and it lands in the reporting inbox (Megan
# 2026-09-03). Read off the real thing on 2026-09-03 -- 174 of them on file,
# from security.info@saraplus.com, subject "SARA Plus Passcode", body "Your
# temporary SARA Plus security code is: <6 digits>".
#
# BY SENDER, not by the word "saraplus": this inbox also receives the Hub's
# own commit-summary emails, and those quote code and commit messages that
# mention SaraPlus all day. A broad text search would eventually read six
# digits out of one of those and type it in as a passcode.
VERIFY_QUERY = "from:security.info@saraplus.com newer_than:1d"
VERIFY_TIMEOUT_S = 180
VERIFY_POLL_S = 10

# Login page fields. The code step's own field is found by LABEL at run time
# (its id is unknown and an unknown id is not worth guessing at).
FIELD_USERNAME = "#ctl00_MainContent_txtUserName"
FIELD_PASSWORD = "#ctl00_MainContent_txtPassword"
BUTTON_LOGIN = "#MainContent_btnLogin"

HUB_PATH = "Reports/ReportingHub.aspx"

# READ OFF THE LIVE PAGE 2026-09-03, in a real browser, with Megan signed in
# as Carlos. Everything before that was inferred from a Loom screenshot and
# most of it was wrong.
#
# The tab strip is ONE multi-level RadTabStrip (ctl00_MainContent_rtsReportOptions):
#   level 1: Sales Dashboard | Install Dashboard | Wireless Dashboard | Detail Reports
#   level 2 (under Detail Reports): Sales Order History | Pending Orders | WSC | ...
# 'Detail Reports' is a CONTAINER -- its pageView is null and clicking it does
# nothing on the server. The CHILD is what loads the panel, so that is the
# only tab this report clicks.
# HOW THE PANEL IS OPENED: by raising the tab strip's own postback, not by
# clicking. Captured off the wire on 2026-09-03 by hooking XMLHttpRequest in a
# real browser while a human clicked the tab:
#
#     __EVENTTARGET   = ctl00$MainContent$rtsReportOptions
#     __EVENTARGUMENT = {"type":0,"index":"3:0"}
#
# '3:0' is the HIERARCHICAL index -- Detail Reports (level-1 #3) then Sales
# Order History (its child #0). An earlier attempt sent '3' on its own and the
# page came back with no tab strip at all.
#
# Clicking is not an option here: patchright evaluates in an isolated world,
# so neither Telerik's $find nor the page's __doPostBack is reachable, and the
# child tab is not even in the DOM until its parent is expanded. Setting two
# hidden fields and submitting the form is plain DOM work that needs none of
# that. The INDEX IS THE ONE POSITIONAL THING HERE, which is why every run
# verifies the panel actually loaded rather than trusting it.
TAB_POSTBACK_TARGET = "ctl00$MainContent$rtsReportOptions"
TAB_POSTBACK_ARG = '{"type":0,"index":"3:0"}'
FORM_ID = "frmMaster"

# Kept only as landmarks for page_state's "where am I actually" line -- no
# longer clicked. 'Detail Reports' is a CONTAINER tab (pageView null, nothing
# happens on the server) and its child is not even in the DOM until it is
# expanded, which is why the panel is opened by postback instead.
TAB_DETAIL_REPORTS = "Detail Reports"
TAB_SALES_ORDER_HISTORY = "Sales Order History"

# The panel itself. Its presence in the DOM is the honest 'are we there yet' --
# far better than the tab's rtsSelected class, which reported Sales Order
# History as selected the whole time the Sales Dashboard was on screen.
PANEL_ORDER_HISTORY = "MainContent_rpvOrderHistory"

# RadDatePicker base ids on THIS panel. Not the Order Dashboard's
# rdpOrderDash* -- reading those was how a run believed it was on Sales Order
# History while looking at the Sales Dashboard.
FIELD_START = "ctl00_MainContent_rdpOrderHistoryStartDate"
FIELD_END = "ctl00_MainContent_rdpOrderHistoryEndDate"

# Customer Type. DEFAULTS TO 'Residential' -- so leaving it alone quietly
# returns residential orders and finds no B2B customers at all. Carlos:
# "for the customer type, we would click on both". Selecting it AUTOPOSTS BACK.
COMBO_CUSTOMER_TYPE = "ctl00_MainContent_rcbCustomerType_SalesOrderHistory"
CUSTOMER_TYPE_BOTH = "Both"

SUBMIT = "#MainContent_btnUpdateOrderHistory"

# RadGrid renders its header and its rows as TWO tables. Reading 'the table
# whose first row holds the headers' finds only the header table, which has no
# data in it.
GRID_HEADER = "ctl00_MainContent_rgOrderHistory_ctl00_Header"
GRID_DATA = "ctl00_MainContent_rgOrderHistory_ctl00"

# Column labels. 146 columns come back and the Report View toggle only changes
# which are VISIBLE -- every one stays in the DOM, so the phone is readable
# without opening a single customer card. That is the whole reason this report
# does not click 'View Customer' the way the Loom did: same number, no page
# load per customer.
COL_ORDER_ID = "Order ID"
COL_ORDER_DATE = "Order Date"
COL_REP = "User Name"
COL_BUSINESS = "Business Name"
COL_CUSTOMER = "Customer Name"
COL_PHONE = "Phone"
REQUIRED_COLUMNS = [COL_ORDER_ID, COL_ORDER_DATE, COL_REP, COL_BUSINESS,
                    COL_CUSTOMER, COL_PHONE]

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
# ONE CHANNEL. The Loom said "the A players and the B2B chat", which read as
# both of Carlos's channels; asked directly he narrowed it (2026-09-02): "it
# can be posted in the aplayers slack in the b2b metrics thread". So
# #alphalete-gp-sales is deliberately NOT in this list -- b2b_dispositions
# posts to both, this does not.
CHANNELS = ["C0AJQA8P716"]
CHANNEL_LABEL = {
    "C0AJQA8P716": "#a-players-b2b",
}

# No iMessage. Carlos, same thread: "we dont need a text. slack works."

# THE POST'S WORDING, IN CARLOS'S WORDS. Asked "what do you want the message
# to say" he answered with this one sentence (2026-09-02), so it is the
# heading and nothing else is invented around it.
#
# It says "wrap up text" and the CHECK is still the Loom's -- "see if there
# was a text message received with that customer's phone number, name, or
# business name". Those texts are the wrap-ups; he is naming the message, not
# narrowing the test. Don't "fix" the mismatch by making the check
# wrap-up-only (Megan corrected exactly that reading, 2026-09-03).
# NO ASTERISKS: ensure_named_thread bolds the title itself and appends the
# date, so markup here would render as **double** stars.
# Emoji-then-title is the house format for a Slack post.
# [[feedback_metrics_slack_format]]
SLACK_HEADER = ":telephone_receiver: Customers who didn\'t receive wrap up text"

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
            "deliberately not used here. Put them on the machine that has "
            "the password with `python -m automations.rc_contact_sync."
            "set_credentials --push \"Lucy 2\"` (hidden prompt, nothing "
            "echoed), move an existing copy with `lucy push_cred_file "
            "saraplus-creds-b2b \"Lucy 2\" --machine \"<box that has "
            "them>\"`, or export SARA_PLUS_B2B_EMAIL / SARA_PLUS_B2B_PASSWORD."
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
