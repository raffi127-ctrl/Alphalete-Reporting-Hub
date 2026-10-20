"""Every id, path and channel the Raf wrap-up check touches, in one place.

This is the Raf-office twin of rc_contact_sync.config, with three differences:
the RingCentral account is Dylan's (rc_autoread's, not Taylor's), the Slack
destination is #alphalete-sales (one channel, not the two B2B ones), and there
is no contacts step, so no contact-dedup state file.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, Optional

CONFIG_DIR = Path.home() / ".config" / "recruiting-report"

# --- the Lucy 1 -> run-box handoff -------------------------------------------
# Raf's FULL Sales Order History (all reps) lands here as one base64-chunked
# JSON envelope {"pulled","start","end","rows","csv"}, written by pull_raf.py
# on Lucy 1 and read by customers.py anywhere. The same control sheet
# sp_order_log / rc_contact_sync already relay through; a DISTINCT tab from
# raf_guest's "Raf Guest Orders" because that one is roster-filtered to
# Carlos's guest reps and this report wants everybody.
from automations.rc_contact_sync.status_probe import CONTROL_SHEET  # noqa: E402
TAB = "Raf All Orders"
# A pull is good for ~a day — the 4am refresh already holds all of yesterday's
# orders. Past this the run refuses the data loudly rather than posting
# week-old names. Mirrors raf_guest.MAX_AGE_H.
MAX_AGE_H = 26
# How wide Lucy 1 pulls. A few days of Order Date so a daily run always has
# yesterday in full; the run then filters to the day it cares about.
PULL_WINDOW_DAYS = 7

# Order types to DROP before the wrap-up check (Dylan 2026-10-20: exclude
# internet upgrades — they are an existing customer upgrading, not a fresh
# sale that owes a wrap-up text). The SaraPlus export's "Order Type" column
# holds exactly "New" / "Upgrade"; matched case-insensitively. Looked up
# tolerantly so a spacing/casing change in the header still finds it.
ORDER_TYPE_COLS = ("Order Type",)
EXCLUDE_ORDER_TYPES = {"upgrade"}

# Product categories on the report (Dylan 2026-10-20: show each customer's
# products as just Internet / TV / Wireless, not the package names). A category
# is tagged when its column is populated on the order: Internet = a non-empty
# "Internet Package", TV = a non-empty "Video Package" (DirecTV), Wireless = a
# "Wireless Line Count" above zero. Columns looked up tolerantly.
PRODUCT_INTERNET_COLS = ("Internet Package",)
PRODUCT_TV_COLS = ("Video Package",)
PRODUCT_WIRELESS_COUNT_COLS = ("Wireless Line Count",)

# --- RingCentral (DYLAN's account — rc_autoread's, NOT Taylor's) -------------
# The app, JWT and watched line all come from automations/rc_autoread/run.py
# so there is exactly one copy of those secrets. owner_id (the JWT's `sub`) is
# Dylan's extension; EXTENSION_ID is the SMS line rc_autoread reads
# (+1 214-845-6450). The identity guard compares the token's owner_id to this.
RC_BASE_URL = "https://platform.ringcentral.com"
EXPECTED_OWNER_ID = "62672491016"   # JWT sub in rc_autoread.run.JWT_TOKEN
WATCH_EXTENSION_ID = "62883924016"  # rc_autoread.run.EXTENSION_ID — the line
WATCH_LINE_LABEL = "Dylan's line (+1 214-845-6450)"

# --- Slack -------------------------------------------------------------------
# #alphalete-sales (Dylan 2026-10-20). One channel, same house format as the
# B2B report: an emoji-then-title HEADER and the names as a threaded reply.
CHANNELS = ["C068PH3RFSM"]
CHANNEL_LABEL = {"C068PH3RFSM": "#alphalete-sales"}

# THE POST'S WORDING (Dylan 2026-10-20: "reps that didn't send wrap ups" — it
# reads from the rep's side, since the parent post lists the reps and the whole
# point is accountability). The check underneath is still "was the customer
# EVER messaged on the line". No asterisks: ensure_named_thread bolds the title
# and appends the date, so markup here would double the stars.
SLACK_HEADER = ":telephone_receiver: Reps that didn\'t send wrap ups"

# --- state -------------------------------------------------------------------
# Header already posted per "day|channel" -> thread_ts, so a same-day rerun
# replies under the morning's header instead of opening a second one. Its own
# filename, never shared with Carlos's report. (No contact-dedup state file:
# this mirror does not create contacts.)
THREAD_STATE_PATH = CONFIG_DIR / "rc_contact_sync_raf_threads.json"


def yesterday(now: Optional[dt.datetime] = None) -> dt.date:
    return (now or dt.datetime.now()).date() - dt.timedelta(days=1)


def saved_thread_ts(day: dt.date, chan: str) -> Optional[str]:
    """The header this box already posted for day+channel, or None.
    Unreadable/missing file = None: never block a post over it."""
    try:
        blob = json.loads(THREAD_STATE_PATH.read_text(encoding="utf-8"))
        return blob.get("%s|%s" % (day.isoformat(), chan)) or None
    except Exception:                                      # noqa: BLE001
        return None


def save_thread_ts(day: dt.date, chan: str, ts: str) -> None:
    """Best effort; keeps the last ~20 keys so the file stays small."""
    try:
        try:
            blob = json.loads(THREAD_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            blob = {}
        blob["%s|%s" % (day.isoformat(), chan)] = ts
        for k in sorted(blob)[:-20]:
            blob.pop(k, None)
        THREAD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        THREAD_STATE_PATH.write_text(json.dumps(blob, indent=2),
                                     encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass


def rc_creds() -> Dict[str, str]:
    """Dylan's RingCentral app credentials, read from rc_autoread so the JWT
    lives in exactly one place. Shaped like rc_contact_sync.rc_creds()'s return
    so rc_contact_sync.ringcentral.token_info() takes it unchanged."""
    from automations.rc_autoread import run as rc
    return {"client_id": rc.CLIENT_ID,
            "client_secret": rc.CLIENT_SECRET,
            "jwt": rc.JWT_TOKEN,
            "expected_owner_id": EXPECTED_OWNER_ID,
            "watch_extension_id": WATCH_EXTENSION_ID}
