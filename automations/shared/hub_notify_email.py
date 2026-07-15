"""Tiny shared sender for Hub owner-notification emails.

Two features use it — the on-upload notice (shared library publishes) and the
direct-push watcher (commits landing on GitHub outside the Hub). Both email the
same owner inbox, from the same account, so the SMTP boilerplate lives here once.

Credential + from-address are the repo's canonical ones (reused, not re-declared):
  FROM  alphaletereporting@gmail.com
  PW    ~/.config/recruiting-report/gmail-app-password  (or env, see email_send)

Sending is best-effort by contract: callers wrap this so a mail hiccup never
blocks a publish or a poll. Set dry_run=True to write the .eml to output/logs
and skip the network (used by --dry-run on both features).
"""
from __future__ import annotations

import datetime as dt
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

# The owner inbox. Same address the intake/bug/glitch Apps Script already emails
# (GLITCH_RECIPIENTS / BUG_INTAKE_RECIPIENT), kept in ONE place here.
NOTIFY_TO = ["meganhidalgo1191@gmail.com"]

_EML_DIR = Path(__file__).resolve().parents[2] / "output" / "logs"


def _ssl_context() -> ssl.SSLContext:
    # Prefer certifi's CA bundle: python.org 3.14 builds can't always see the
    # system roots, which breaks Gmail's TLS (a real failure mode on the mini —
    # see day_orchestrator/notify.py). Fall back to the default context.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def send_html(subject: str, html_body: str, text_body: str,
              to: list[str] | None = None, *, dry_run: bool = False,
              tag: str = "hub-notify") -> None:
    """Send a multipart (text + HTML) email from the reporting account.

    Raises on a real send failure so callers can log it; callers are expected to
    swallow it (best-effort). dry_run writes an .eml and returns without sending.
    """
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)

    recipients = list(to or NOTIFY_TO)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    if dry_run:
        _EML_DIR.mkdir(parents=True, exist_ok=True)
        eml = _EML_DIR / f"{tag}-{dt.datetime.now():%Y%m%d-%H%M%S}.eml"
        eml.write_bytes(bytes(msg))
        print(f"[hub-notify] DRY-RUN — wrote {eml} (would send to "
              f"{', '.join(recipients)})", flush=True)
        return

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=_ssl_context()) as s:
        s.login(FROM_ADDR, app_password())
        s.send_message(msg)
    print(f"[hub-notify] sent '{subject}' to {', '.join(recipients)}", flush=True)
