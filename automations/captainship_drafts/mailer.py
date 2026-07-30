"""Hand the built captainship reports to Gmail over SMTP.

WHY SMTP AND NOT THE GMAIL API (Eve, 2026-07-30). The whole flow moved onto the
mini so the captains stop depending on Eve's laptop happening to be awake. The
mini has alphaletereporting's app password — it mails the Org Sales Board with
it every day — and it does NOT have the gmail.compose OAuth token, which only
ever existed on Eve's box. Seeding that token onto a machine nobody sits at
would mean an interactive consent screen and a live credential transiting the
control Sheet; the app password is already there.

The message that arrives is the same either way: both paths submit the exact
MIME we built. That matters more here than anywhere else in the repo — the
inline images ARE the report, and the reviewed .eml is mailed byte-for-byte
(see run._send_reviewed). Nothing in this module builds or edits a message; it
only carries one.

    from automations.captainship_drafts.mailer import Mailer

    with Mailer() as m:            # one login for all 12
        m.send(msg)               # per-captain failures stay per-captain

A dead connection mid-run reconnects once rather than taking the remaining
captains down with it: twelve messages of a few MB each is exactly the shape of
run where a server-side idle disconnect lands in the middle.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import Message

from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password,
)


def _ssl_context():
    # certifi's CA bundle — the python.org macOS build ships without system CAs,
    # so a default context fails verification on the mini. Same as
    # org_sales_board.screenshot_email.send.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class Mailer:
    """An authenticated Gmail SMTP session, opened on first use."""

    def __init__(self, *, logfn=print):
        self._conn = None
        self._logfn = logfn

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "Mailer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _connect(self):
        conn = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=_ssl_context())
        conn.login(FROM_ADDR, app_password())
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.quit()
        except Exception:       # noqa: BLE001 — a closed socket is not a failure
            pass
        self._conn = None

    # -- the one thing it does --------------------------------------------
    def send(self, msg: Message) -> None:
        """Submit `msg`. Recipients come from its own To/Cc headers.

        A From is filled in only when the message has none — Gmail rejects a
        submission whose sender isn't the account that logged in, and the
        reviewed .eml always carries FROM_ADDR already."""
        if not (msg["From"] or "").strip():
            msg["From"] = FROM_ADDR
        conn = self._conn or self._connect()
        try:
            conn.send_message(msg)
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError):
            # Reconnect once. Anything else (a refused recipient, an auth
            # failure) is the caller's to report per captain — retrying it would
            # only produce the same answer more slowly.
            self._logfn("  … SMTP connection dropped — reconnecting")
            self.close()
            self._connect().send_message(msg)


def send_one(msg: Message, *, logfn=print) -> None:
    """Mail a single message. For one-off sends; the 12-report run uses Mailer
    so it logs in once."""
    with Mailer(logfn=logfn) as m:
        m.send(msg)
