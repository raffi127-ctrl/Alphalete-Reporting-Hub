"""Email a BOX Order Log to an owner who wants it by mail instead of Slack.

Some BOX owners (starting with Roshan Amin Ahmad, 2026-07-29) get their OWN
office's order log by email rather than reading a Slack thread. run_owner.py
builds the owner-scoped workbook + payout image and hands them here.

Sends from alphaletereporting@gmail.com over Gmail SMTP (SSL, port 465) using
the reporting account's App Password, reusing the exact SMTP plumbing the
Scheduled-6-days-out report already uses (FROM_ADDR / SMTP_HOST / SMTP_PORT /
app_password) so the credential lives in one place.

Attaches the two daily artifacts, same as Carlos's Slack thread but scoped to
the one owner:
  * the per-rep workbook  (the owner's office: overall log + one tab per rep)
  * the payout image      (accepted by supplier, last week & this week)

DRY-RUN writes the .eml to output/logs and sends nothing. Python 3.9 lives on
Lucy 2, so annotations stay deferred and there's no runtime `X | Y`.
"""
from __future__ import annotations

import mimetypes
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional

_EML_DIR = Path(__file__).resolve().parents[2] / "output" / "logs"


def _ssl_context() -> ssl.SSLContext:
    # certifi first: python.org builds on the mini/Lucy 2 can't always see the
    # system CA roots, which breaks Gmail's TLS (see hub_notify_email.py).
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _attach(msg: EmailMessage, path: Path) -> None:
    """Attach `path` with a best-guess MIME type (defaults to octet-stream)."""
    ctype, _ = mimetypes.guess_type(str(path))
    maintype, subtype = (ctype.split("/", 1) if ctype
                         else ("application", "octet-stream"))
    msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype,
                       filename=path.name)


def build_message(subject: str, xlsx_path: Path, png_path: Path,
                  to_addrs: List[str], greeting_name: str = "") -> EmailMessage:
    """Build the email: short plain-text note + the workbook and payout image
    attached. Kept plain-text on purpose — it's a data hand-off; the numbers
    live in the attachments."""
    from automations.scheduled_6_days_out.email_send import FROM_ADDR

    hi = "Hi {},".format(greeting_name) if greeting_name else "Hi,"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(
        "{}\n\n"
        "Here's your BOX Order Log for today:\n\n"
        "  • Overall log + a tab per rep (your office)\n"
        "  • Accepted by supplier — last week & this week\n\n"
        "This covers your office only.\n\n"
        "— Alphalete Reporting\n".format(hi)
    )
    for p in (xlsx_path, png_path):
        if p and Path(p).exists():
            _attach(msg, Path(p))
    return msg


def send(subject: str, xlsx_path: Path, png_path: Path,
         to_addrs: List[str], *, greeting_name: str = "",
         dry_run: bool = False, logfn=print) -> dict:
    """Email one owner their BOX Order Log.

    dry_run: build + write the .eml to output/logs, send nothing.
    Returns a small status dict either way; raises on a real send failure so
    the caller can log it (email is best-effort — it never blocks a run).
    """
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)

    to_addrs = [a for a in (to_addrs or []) if a]
    if not to_addrs:
        logfn("  (no email recipients — skipping)")
        return {"skipped": True, "reason": "no recipients"}

    msg = build_message(subject, xlsx_path, png_path, to_addrs, greeting_name)

    if dry_run:
        _EML_DIR.mkdir(parents=True, exist_ok=True)
        eml = _EML_DIR / "box_order_log_email_{}.eml".format(
            (greeting_name or to_addrs[0]).split()[0].lower())
        eml.write_bytes(bytes(msg))
        logfn("  [dry-run] email NOT sent. Wrote {} ({} recipient(s): {})"
              .format(eml, len(to_addrs), ", ".join(to_addrs)))
        return {"dry_run": True, "to": to_addrs, "eml": str(eml)}

    ctx = _ssl_context()
    import smtplib
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
            s.login(FROM_ADDR, app_password())
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(
            "Gmail rejected the login for {} — check the App Password / "
            "2-Step Verification. ({})".format(FROM_ADDR, e)) from e
    logfn("  \U0001F4E7 Emailed BOX Order Log to {}".format(", ".join(to_addrs)))
    return {"sent": True, "to": to_addrs}
