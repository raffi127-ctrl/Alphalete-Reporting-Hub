"""Read First Advantage / Sterling background-check emails from raffi127@gmail.com
over IMAP (unattended, app-password auth) and return parsed BGEvents.

Mirrors automations/shared/email_ingest.py, but points at a DIFFERENT account
(raffi127, where all the fadv emails land) with its OWN app-password file, and
returns parsed status events instead of attachments. Read-only on All Mail.

App password lives at ~/.config/recruiting-report/gmail-app-password-raffi127
(override account/path via env BGSYNC_IMAP_ACCOUNT / BGSYNC_IMAP_APPPW_PATH so
the reception inbox can be swapped in without a code change).
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import os
import re
from email.header import decode_header
from pathlib import Path
from typing import List, Optional

from automations.bg_check_sync import parse
from automations.bg_check_sync.parse import BGEvent

IMAP_HOST = "imap.gmail.com"
ACCOUNT = os.environ.get("BGSYNC_IMAP_ACCOUNT", "raffi127@gmail.com")
APP_PW_PATH = Path(os.environ.get(
    "BGSYNC_IMAP_APPPW_PATH",
    str(Path.home() / ".config" / "recruiting-report" / "gmail-app-password-raffi127")))
FADV_SENDER = "fadv.co"  # matches noreply@us.fadv.co and NoReply@us.fadv.co


def _app_password() -> str:
    if not APP_PW_PATH.exists():
        raise RuntimeError(
            f"Gmail app password not found at {APP_PW_PATH}. This is the app "
            f"password for {ACCOUNT} (Google Account -> Security -> App passwords). "
            f"Save the 16-char code there.")
    return APP_PW_PATH.read_text(encoding="utf-8-sig").strip().replace(" ", "")


def _decode(s: str) -> str:
    return "".join(
        t.decode(enc or "utf-8", "replace") if isinstance(t, bytes) else t
        for t, enc in decode_header(s or ""))


_TAG_RE = re.compile(r"<[^>]+>")


def _best_text(msg) -> str:
    """Return readable text for classification: prefer text/plain, else strip
    tags from text/html. fadv result emails are HTML-only, so we usually strip."""
    plain, html_body = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_content_disposition() == "attachment":
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if ctype == "text/plain":
                plain += text
            elif ctype == "text/html":
                html_body += text
    else:
        try:
            payload = msg.get_payload(decode=True)
            text = payload.decode(msg.get_content_charset() or "utf-8", "replace")
        except Exception:
            text = msg.get_payload() or ""
        if msg.get_content_type() == "text/html":
            html_body = text
        else:
            plain = text
    if plain.strip():
        return plain
    # strip tags but keep the "…of Last, First</a>" link text (regex stops at '<')
    return _TAG_RE.sub(" ", html_body)


def _connect() -> imaplib.IMAP4_SSL:
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(ACCOUNT, _app_password())
    M.select('"[Gmail]/All Mail"', readonly=True)
    return M


def fetch_events(since_days: int = 30, verbose: bool = True) -> List[BGEvent]:
    """Fetch + parse every fadv background-check email in the window. Returns the
    BGEvents that classify to a real per-candidate status (bulk-invite / auth-code
    emails classify to None and are dropped)."""
    M = _connect()
    try:
        since = (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(FROM "{FADV_SENDER}" SINCE {since})')
        ids = (data[0] or b"").split()
        events: List[BGEvent] = []
        for mid in ids:
            typ, msg_data = M.fetch(mid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            sender = _decode(msg.get("From", ""))
            subject = _decode(msg.get("Subject", ""))
            date = msg.get("Date", "")
            iso = _to_iso(date)
            body = _best_text(msg)
            ev = parse.classify(sender, subject, body, date=iso, source_id=mid.decode())
            if ev:
                events.append(ev)
        if verbose:
            print(f"[email_source] {ACCOUNT}: {len(ids)} fadv emails since {since}, "
                  f"{len(events)} status events parsed")
        return events
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _to_iso(date_hdr: str) -> str:
    """RFC2822 email Date -> sortable ISO string; fall back to the raw header."""
    try:
        d = email.utils.parsedate_to_datetime(date_hdr)
        return d.astimezone(dt.timezone.utc).isoformat()
    except Exception:
        return date_hdr or ""
