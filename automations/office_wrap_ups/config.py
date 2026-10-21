"""Which offices to run, their channels, and the shared RingCentral line.

Channels come from the canonical roster (office_metrics.OFFICES) so there is
one source of truth — if an office's channel moves, this follows. The
RingCentral line + identity are reused from rc_contact_sync_raf (Dylan's line).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

# Reuse Dylan's RingCentral line + identity from the Raf report (one line for
# every office — Dylan 2026-10-21).
from automations.rc_contact_sync_raf import config as RAF

CONFIG_DIR = Path.home() / ".config" / "recruiting-report"

RC_BASE_URL = RAF.RC_BASE_URL
EXPECTED_OWNER_ID = RAF.EXPECTED_OWNER_ID
WATCH_EXTENSION_ID = RAF.WATCH_EXTENSION_ID
WATCH_LINE_LABEL = RAF.WATCH_LINE_LABEL
rc_creds = RAF.rc_creds

# Same wording as the Raf report (Dylan 2026-10-20).
SLACK_HEADER = ":telephone_receiver: Reps that didn\'t send wrap ups"

# Tag Dylan at the bottom of every reply so the morning post is readily visible
# to him (Dylan 2026-10-21). A Slack mention only works with the user's id FROM
# THAT WORKSPACE, so AO channels use his AO id and a different-workspace office
# (Trang → FRESH SUCCESS) uses his id there, keyed by the office's token file.
TAG_USER_ID = "U048V0YA5FC"  # Dylan Twaddle, AO workspace
TAG_USER_ID_CROSSWS = {
    # token file -> Dylan's user id in that workspace. He is in FRESH SUCCESS
    # too (Dylan 2026-10-21) — fill his member id there to tag him in Trang's
    # #freshsuccess-all-leaders.
    # "slack-token-freshsuccess": "U_________",
}

# The offices this report covers, by office_metrics.OFFICES key. Every one is an
# owner in Raf's captainship. Hammad + Salik share #elite-prime-sales.
OFFICE_KEYS = ["haytham", "trang", "hammad", "jacob", "joseph", "kash",
               "rashad", "aya", "cyrus", "nii", "cody", "salik"]

# Tableau "Owner Name" spellings to match per office, when they differ from or
# add to the roster owner. Only exceptions need an entry; everything else
# matches on the roster's `owner` field.
OWNER_ALIASES: Dict[str, List[str]] = {
    # Salik Mallick's office shows up under both spellings in the Order Log
    # (same as disconnects.run.RAF_OWNERS).
    "salik": ["Salik Mallick", "Salik Malik"],
}

# Order-Date pull window. We report a single target day but pull a few days so
# a Tableau refresh lag can't drop yesterday's orders entirely.
PULL_WINDOW_DAYS = 3

# Header-post dedup, per "day|channel" -> thread_ts (so a same-day re-run
# replies under the morning's header instead of opening a second one).
THREAD_STATE_PATH = CONFIG_DIR / "office_wrap_ups_threads.json"


def office_profiles(only: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """[{key, owner, owner_aliases, channel_id, channel_name, slack_token_file}]
    resolved from office_metrics.OFFICES. `only` limits to those keys."""
    from automations.office_metrics import offices as OM
    off = OM.OFFICES
    keys = [k for k in OFFICE_KEYS if (only is None or k in only)]
    out: List[Dict[str, str]] = []
    for k in keys:
        v = off.get(k)
        if not v:
            continue
        owner = (getattr(v, "owner", "") or "").strip()
        out.append({
            "key": k,
            "owner": owner,
            "owner_aliases": OWNER_ALIASES.get(k, [owner]) if owner else
                             OWNER_ALIASES.get(k, []),
            "channel_id": getattr(v, "channel_id", "") or "",
            "channel_name": getattr(v, "channel_name", "") or k,
            "slack_token_file": getattr(v, "slack_token_file", "") or "",
        })
    return out


def yesterday(now: Optional[dt.datetime] = None) -> dt.date:
    return (now or dt.datetime.now()).date() - dt.timedelta(days=1)


def saved_thread_ts(day: dt.date, chan: str) -> Optional[str]:
    try:
        blob = json.loads(THREAD_STATE_PATH.read_text(encoding="utf-8"))
        return blob.get("%s|%s" % (day.isoformat(), chan)) or None
    except Exception:                                      # noqa: BLE001
        return None


def save_thread_ts(day: dt.date, chan: str, ts: str) -> None:
    try:
        try:
            blob = json.loads(THREAD_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            blob = {}
        blob["%s|%s" % (day.isoformat(), chan)] = ts
        for k in sorted(blob)[:-60]:
            blob.pop(k, None)
        THREAD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        THREAD_STATE_PATH.write_text(json.dumps(blob, indent=2),
                                     encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass
