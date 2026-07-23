"""Monday recognition reminder — via EMAIL.

Maud's ask (relayed by Megan 2026-07-21): each Monday remind the owners/ICDs to fill
in their office promotions on the recognition sheet before the Leader's Call. Originally
built for the "Alphalete Ownrs 🔥" iMessage group, switched to EMAIL 2026-07-21 (the
iMessage group send is no longer available — and email needs no chat GUID / Full Disk
Access). Sends Mon 11:00am, 4:00pm, and 7:15pm (final call) CST from the reporting Gmail.

  python -m automations.owners_call_reminder.run            # dry-run — writes an .eml, sends nothing
  python -m automations.owners_call_reminder.run --send     # actually email
  python -m automations.owners_call_reminder.run --final    # force the FINAL CALL wording
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as _html
import os
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

# Who the reminder goes to: the "Org. Call Invite" Google Contacts distro (Megan
# maintains it — membership changes are picked up automatically each run).
# OWNERS_CALL_EMAILS (comma-separated) overrides it for testing.
DISTRO_GROUP = os.environ.get("OWNERS_CALL_GROUP", "Org. Call Invite")


def _recipients():
    """(emails, problems). Env override wins; else expand the Contacts distro."""
    env = [e.strip() for e in os.environ.get("OWNERS_CALL_EMAILS", "").split(",") if e.strip()]
    if env:
        return env, []
    try:
        from automations.shared.contacts_auth import expand_groups
        emails, missing = expand_groups([DISTRO_GROUP])
        return emails, [f"contacts group {g!r} not found" for g in missing]
    except Exception as e:  # noqa: BLE001
        return [], [f"couldn't read the {DISTRO_GROUP!r} distro "
                    f"({type(e).__name__}: {str(e)[:120]})"]

# The recognition sheet ICDs fill in (same link Maud sends). See recognition_tab.
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1lgYjfpCwYbeeGAdx7FEyI9PIqFk-W57X7HaZ4nsuoFM/edit?usp=sharing")

SUBJECT = "Reminder: fill out the recognition sheet 🐺"
FINAL_SUBJECT = "🚨 FINAL CALL — fill out the recognition sheet"

# The 11am + 4pm reminder.
BODY = (
    "Reminder: the Owner's Call is tonight at 8:15pm CST, followed by the Leader's "
    "Call at 8:45pm CST! 🔥🎉\n"
    "\n"
    "Please make sure to fill out the recognition sheet before the call:\n"
    + SHEET_URL
)
# The 7:15pm "final call" send — last chance before the call.
FINAL_BODY = (
    "🚨 Final call! Last chance to fill out the recognition sheet before tonight's "
    "call. 🔥🎉\n"
    "\n"
    + SHEET_URL
)

_EML_DIR = Path(__file__).resolve().parents[2] / "output" / "owners_call_reminder"


def _is_final_time() -> bool:
    """One plist fires all 3 times; the 7:15pm send uses the FINAL CALL wording."""
    return dt.datetime.now().hour >= 19


def _to_html(text: str) -> str:
    esc = _html.escape(text).replace(_html.escape(SHEET_URL),
                                     f'<a href="{SHEET_URL}">{SHEET_URL}</a>')
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
            'font-size:15px;line-height:1.5;color:#111">'
            + esc.replace("\n", "<br>") + "</div>")


def send(dry_run: bool = True, final: "bool | None" = None) -> int:
    if final is None:
        final = _is_final_time()
    subject = FINAL_SUBJECT if final else SUBJECT
    body = FINAL_BODY if final else BODY

    recipients, problems = _recipients()
    for p in problems:
        print(f"  ⚠ {p}", flush=True)
    if not recipients:
        print(f"NO RECIPIENTS — the {DISTRO_GROUP!r} distro resolved to 0 emails "
              "(or set OWNERS_CALL_EMAILS). Not sending.", flush=True)
        return 2

    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    msg.add_alternative(_to_html(body), subtype="html")

    if dry_run:
        _EML_DIR.mkdir(parents=True, exist_ok=True)
        eml = _EML_DIR / f"reminder-{'final' if final else 'regular'}-{dt.date.today().isoformat()}.eml"
        eml.write_bytes(bytes(msg))
        print(f"[dry-run] WOULD email {len(recipients)} recipient(s) from the "
              f"{DISTRO_GROUP!r} distro ({'FINAL CALL' if final else 'regular'}). "
              f"Preview: {eml}\n"
              f"Subject: {subject}\n"
              f"------------------------------------------------------------\n"
              f"{body}\n"
              f"------------------------------------------------------------\n"
              f"To ({len(recipients)}): {', '.join(recipients[:4])}"
              f"{', …' if len(recipients) > 4 else ''}", flush=True)
        return 0

    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    import smtplib
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(FROM_ADDR, app_password())
        s.send_message(msg)
    print(f"✅ {'Final-call' if final else 'Reminder'} emailed to "
          f"{len(recipients)} recipient(s) from the {DISTRO_GROUP!r} distro.", flush=True)
    # Each sent reminder is one step of the Monday Leader's Call flow — publish a
    # success so that card's pill climbs (1/4 → 3/4 amber; the 7:30pm deck is 4/4
    # green). Best-effort: a Hub write must never fail the send.
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("owners_call_reminder",
                                 "Leader's Call — Monday reminder", status="success")
    except Exception:
        pass
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Email the owners/ICDs the Monday "
                                             "recognition reminder.")
    ap.add_argument("--send", action="store_true",
                    help="Actually send (default is a dry-run that writes an .eml).")
    ap.add_argument("--final", action="store_true",
                    help="Force the FINAL CALL wording (else auto-picked: 7pm+ = final).")
    args = ap.parse_args()
    return send(dry_run=not args.send, final=True if args.final else None)


if __name__ == "__main__":
    sys.exit(main())
