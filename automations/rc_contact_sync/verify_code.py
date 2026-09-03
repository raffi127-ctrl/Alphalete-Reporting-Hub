"""Read the SaraPlus login verification code out of the reporting inbox.

SaraPlus emails a code on login and Carlos has it filtered to
alphaletereporting@gmail.com (Megan 2026-09-03: "that's what carlos is sending
the reporting email so that you can login each time if needed"). Unattended
login therefore means: submit the password, then go and read the code.

THE ONLY HARD RULE HERE IS THE CLOCK. A code email that was already sitting in
the inbox when we pressed the button is a code for somebody else's login, or
for ours an hour ago -- both expired, both would be typed in with total
confidence and fail as "wrong password", which is the single most misleading
error this report could produce. `since` is the instant the login was
submitted, and anything older than it is ignored even if it is the only code
in the mailbox.

Read-only: the mailbox is opened readonly and nothing is marked, moved or
deleted. Reuses shared.email_ingest's account + app password -- the same
credential every other inbox reader here uses.
[[reference_hub_source_email_access]]
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import re
import time
from email.utils import parsedate_to_datetime
from typing import List, Optional, Tuple

from automations.shared import email_ingest as _ing

# Gmail search, not IMAP's: we know this mailbox is Gmail, and X-GM-RAW lets
# the query say what a human would type in the search box. Kept broad on
# purpose -- matching the SENDER would be tighter, but nobody has told us what
# SaraPlus sends from, and a wrong sender means silently never finding a code.
GMAIL_QUERY = "saraplus OR sara+ newer_than:1d"

# The code itself. SaraPlus's exact wording is unknown, so the labelled forms
# are tried first and a bare digit-run only as a fallback -- that ordering is
# what stops a phone number or an order id in the footer being read as a code.
LABELLED = [
    re.compile(r"(?:verification|security|access|login|one[- ]time)\s*"
               r"(?:code|pin)\D{0,20}(\d{4,8})", re.I),
    re.compile(r"\bcode\s*(?:is|:)\s*(\d{4,8})", re.I),
    re.compile(r"\b(\d{4,8})\s*is your\b.{0,40}code", re.I),
]
BARE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


class CodeNotFound(RuntimeError):
    pass


def extract_code(text: str) -> Optional[str]:
    """The code in one email's text, or None. Labelled forms win."""
    if not text:
        return None
    for rx in LABELLED:
        m = rx.search(text)
        if m:
            return m.group(1)
    m = BARE.search(text)
    return m.group(1) if m else None


def _body_text(msg) -> str:
    """Subject + every text/plain and text/html part, flattened."""
    parts = [str(msg.get("Subject", ""))]
    if msg.is_multipart():
        walk = msg.walk()
    else:
        walk = [msg]
    for part in walk:
        if part.get_content_maintype() != "text":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            parts.append(payload.decode(part.get_content_charset() or "utf-8",
                                        "replace"))
        except Exception:                                  # noqa: BLE001
            continue
    text = "\n".join(parts)
    # Strip tags so an HTML mail's code isn't buried in markup.
    return re.sub(r"<[^>]+>", " ", text)


def _candidates(M, query: str) -> List[bytes]:
    try:
        typ, data = M.search(None, "X-GM-RAW", '"%s"' % query)
        if typ == "OK":
            return (data[0] or b"").split()
    except Exception:                                      # noqa: BLE001
        pass
    # Non-Gmail / X-GM-RAW refused: fall back to a plain TEXT search.
    since = (dt.date.today() - dt.timedelta(days=1)).strftime("%d-%b-%Y")
    typ, data = M.search(None, '(TEXT "saraplus" SINCE %s)' % since)
    return (data[0] or b"").split()


def _newest_code(since: dt.datetime, query: str) -> Optional[Tuple[str, dt.datetime]]:
    """The newest code in a mail that ARRIVED AFTER `since`, or None."""
    M = imaplib.IMAP4_SSL(_ing.IMAP_HOST)
    try:
        M.login(_ing.ACCOUNT, _ing._app_password())
        M.select('"[Gmail]/All Mail"', readonly=True)
        best = None
        for uid in reversed(_candidates(M, query)):        # newest first
            typ, data = M.fetch(uid, "(RFC822)")
            if typ != "OK" or not data or not data[0]:
                continue
            msg = email.message_from_bytes(data[0][1])
            try:
                when = parsedate_to_datetime(msg.get("Date"))
            except Exception:                              # noqa: BLE001
                continue
            if when is None:
                continue
            if when.tzinfo is None:
                when = when.astimezone()
            if when < since:
                # Sorted newest-first, so everything past here is older too.
                break
            code = extract_code(_body_text(msg))
            if code and (best is None or when > best[1]):
                best = (code, when)
        return best
    finally:
        try:
            M.logout()
        except Exception:                                  # noqa: BLE001
            pass


def wait_for_code(since: dt.datetime, *, timeout_s: int = 180,
                  poll_s: int = 10, query: str = GMAIL_QUERY,
                  log=print) -> str:
    """Poll the inbox until a code newer than `since` shows up.

    `since` should be a moment or two BEFORE the login was submitted -- clocks
    between this machine and Gmail are not identical, and a code discarded for
    being one second too old looks exactly like a code that never arrived."""
    deadline = time.time() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        hit = _newest_code(since, query)
        if hit:
            code, when = hit
            log("  verification code received %s (attempt %d)"
                % (when.strftime("%H:%M:%S"), attempt))
            return code
        if time.time() >= deadline:
            raise CodeNotFound(
                "no SaraPlus verification code reached %s within %ds of the "
                "login (searched Gmail for %r, ignoring anything sent before "
                "%s). Either the code is filtered somewhere other than this "
                "inbox, or it arrives from a sender/wording the search misses "
                "-- open the mailbox, find the real email and set "
                "config.VERIFY_QUERY. Nothing was typed in."
                % (_ing.ACCOUNT, timeout_s, query,
                   since.strftime("%H:%M:%S")))
        log("  waiting for the verification code... (%ds left)"
            % int(deadline - time.time()))
        time.sleep(poll_s)
