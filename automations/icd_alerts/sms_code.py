"""SaraPlus's code by TEXT, read off this Mac's Messages (Eveliz, 2026-10-31).

WHY. Eveliz's SaraPlus codes come by SMS, so the mail forward sara_code.py
waits on can never answer for her. Her iPhone now forwards its texts to her
iMac (Text Message Forwarding ON, screenshot 2026-10-31) and Lucy has Full
Disk Access there (probe-messages: can read yes). So for her office the code
screen is answered from here instead of from Lucy 1:

    pick "Mobile Phone" on the picker -> Get Code -> SaraPlus texts her
    -> the text lands in Messages on this Mac -> read the code out of
    ~/Library/Messages/chat.db -> type it.

READ-ONLY, AND THE TEXT NEVER LEAVES THE MAC. Same read as messages_probe
(mode=ro). Only the code itself is used, and only to type it into SaraPlus.

NOT AT NIGHT. Choosing Mobile makes the owner's phone buzz. Outside
TEXT_HOURS this does not ask: sara_code falls back exactly as before (the
fault, which the poster holds until morning), and tries again on the next
sweep after RETRY_AFTER_MINUTES -- by then inside the hours.

Python 3.9-safe (the office Macs run Apple's 3.9).
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import time
from typing import Optional

from automations.icd_alerts import messages_probe as M

# Offices whose SaraPlus codes come by text -- the ones the probe watches.
TEXT_OFFICES = M.PROBE_KEYS
# Local hours (on the Mac) when it is fine to make the owner's phone buzz.
TEXT_HOURS = (7, 22)
CODE_WAIT_SECONDS = 5 * 60      # a forwarded text lands in seconds; slack for a sleepy Mac
POLL_SECONDS = 5

_CODE_AFTER_WORD = re.compile(r"(?:pass)?code\D{0,25}?(\d{4,8})(?!\d)", re.I)
_BARE_CODE = re.compile(r"(?<![\d\w])(\d{4,8})(?![\d])")
_SARA = re.compile(r"sara\s*(?:\+|plus)|passcode", re.I)


class NoText(RuntimeError):
    """No SaraPlus text with a code reached this Mac."""


def wants_text(office_key: str) -> bool:
    return (office_key or "").strip().lower() in TEXT_OFFICES


def quiet_hours(now: Optional[dt.datetime] = None) -> bool:
    h = (now or dt.datetime.now()).hour
    return not (TEXT_HOURS[0] <= h < TEXT_HOURS[1])


def extract_code(body: str) -> Optional[str]:
    """The code out of one SaraPlus text, or None. The number right after
    "code"/"passcode" first; a lone 4-8 digit number only as a last resort."""
    if not body or not _SARA.search(body):
        return None
    m = _CODE_AFTER_WORD.search(body)
    if m:
        return m.group(1)
    found = _BARE_CODE.findall(body)
    return found[-1] if len(found) == 1 else None


def newest_code(since: dt.datetime, db: str = M.DB) -> Optional[str]:
    """Newest SaraPlus code TEXTED after `since`, or None. Raises NoText if
    Messages cannot be read at all (no Full Disk Access) -- waiting on a
    database we cannot open would only burn the minutes."""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=10)
    except sqlite3.Error as e:
        raise NoText("cannot open Messages: %s" % str(e).split("\n")[0][:120])
    try:
        try:
            rows = con.execute(
                """SELECT m.date, m.text, m.attributedBody
                     FROM message m
                    WHERE m.is_from_me = 0 AND m.date > ?
                      AND COALESCE(m.service, '') = 'SMS'
                    ORDER BY m.date DESC LIMIT 50""",
                (M._apple_value(since),)).fetchall()
        except sqlite3.Error as e:
            raise NoText("cannot read Messages (Full Disk Access?): %s"
                         % str(e).split("\n")[0][:120])
    finally:
        con.close()
    for _when, text, blob in rows:
        code = extract_code(M._body(text, blob))
        if code:
            return code
    return None


def code_from_messages(since: dt.datetime, *, wait_s: int = CODE_WAIT_SECONDS,
                       poll_s: int = POLL_SECONDS, db: str = M.DB,
                       sleep=time.sleep, clock=time.time, log=print) -> str:
    """Wait for SaraPlus's text to land in Messages and return its code."""
    log("  waiting for SaraPlus's text in Messages (since %s)"
        % since.strftime("%H:%M:%S"))
    deadline = clock() + wait_s
    while True:
        code = newest_code(since, db=db)
        if code:
            log("  code read from the text")
            return code
        if clock() >= deadline:
            raise NoText("no SaraPlus text reached this Mac within %d minutes "
                         "(is Text Message Forwarding still on for it?)"
                         % (wait_s // 60))
        sleep(poll_s)
