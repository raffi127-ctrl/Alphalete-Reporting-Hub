"""Create Gmail drafts via the Gmail API — a generic, report-agnostic
helper. Each report builds its own email.message.EmailMessage (subject,
recipients, HTML body, inline images, attachments) and hands it here to
land as a DRAFT in the authorized mailbox. Nothing is sent — a human
reviews the draft in Gmail and sends it.

Auth comes from automations.shared.gmail_auth (a separate gmail.compose
token authorized as alphaletereporting@gmail.com — see that module). The
draft is created in the mailbox of whatever account authorized the token,
so make sure gmail_auth was authorized as the right account.

  from email.message import EmailMessage
  from automations.shared.gmail_draft import create_draft

  msg = EmailMessage()
  msg["Subject"] = "..."; msg["To"] = "a@b.com"; msg.set_content("hi")
  create_draft(msg)          # -> {'draft_id': ..., 'message_id': ...}
  create_draft(msg, dry_run=True)   # build only, no API call
"""
from __future__ import annotations

import base64
from email.message import EmailMessage


def _service():
    """Build an authenticated Gmail API service from the saved token."""
    from googleapiclient.discovery import build
    from automations.shared.gmail_auth import load_credentials

    creds = load_credentials()
    # cache_discovery=False avoids the noisy file_cache warning under
    # oauth2client-less installs (and a write to a non-writable dir).
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def create_draft(msg: EmailMessage, *, dry_run: bool = False,
                 logfn=print) -> dict:
    """Create `msg` as a draft in the authorized mailbox.

    dry_run: encode the message but DON'T call the API — returns the
    subject + recipients + encoded size so a caller can preview safely.

    Returns {'draft_id', 'message_id'} on success, or a preview dict when
    dry_run.
    """
    if not isinstance(msg, EmailMessage):
        raise TypeError("create_draft expects an email.message.EmailMessage")

    # Gmail wants the full RFC-2822 message base64url-encoded in `raw`.
    raw = base64.urlsafe_b64encode(bytes(msg)).decode("ascii")

    to = msg.get("To", "")
    subject = msg.get("Subject", "")

    if dry_run:
        logfn(f"  (dry-run) would create draft: subj={subject!r} "
              f"to={to!r} ({len(raw)} b64 chars)")
        return {"dry_run": True, "subject": subject, "to": to,
                "raw_len": len(raw)}

    service = _service()
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}).execute()
    result = {"draft_id": draft.get("id"),
              "message_id": (draft.get("message") or {}).get("id")}
    logfn(f"  ✓ draft created: id={result['draft_id']} subj={subject!r}")
    return result
