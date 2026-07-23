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

# Who the reminder goes to — comma-separated in OWNERS_CALL_EMAILS, or set the default
# below once Megan provides the owner/ICD list. Empty → refuses to send.
RECIPIENTS = [e.strip() for e in os.environ.get("OWNERS_CALL_EMAILS", "").split(",") if e.strip()]

# The recognition sheet ICDs fill in (same link Maud sends). See recognition_tab.
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1lgYjfpCwYbeeGAdx7FEyI9PIqFk-W57X7HaZ4nsuoFM/edit?usp=sharing")

SUBJECT = "Reminder: fill out the recognition sheet 🐺"
FINAL_SUBJECT = "🚨 FINAL CALL — fill out the recognition sheet"

# Maud's verbatim reminder (the 11am + 4pm sends).
BODY = (
    "Reminder for the Owner's Call tonight at 8:15pm CT and then Leader's Call "
    "following at 8:45pm CT!!!!!! 🔥🎉\n"
    "\n"
    "Make sure to fill out the recognition sheet!\n"
    + SHEET_URL
)
# The 7:15pm "final call" send — last chance before the call.
FINAL_BODY = (
    "🚨 FINAL CALL — last chance to fill out the recognition sheet before tonight's "
    "call!! 🔥🎉\n"
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

    if not RECIPIENTS:
        print("NO RECIPIENTS — set OWNERS_CALL_EMAILS (comma-separated owner/ICD "
              "emails) before this can send.", flush=True)
        return 2

    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(RECIPIENTS)
    msg.set_content(body)
    msg.add_alternative(_to_html(body), subtype="html")

    if dry_run:
        _EML_DIR.mkdir(parents=True, exist_ok=True)
        eml = _EML_DIR / f"reminder-{'final' if final else 'regular'}-{dt.date.today().isoformat()}.eml"
        eml.write_bytes(bytes(msg))
        print(f"[dry-run] WOULD email {len(RECIPIENTS)} recipient(s) "
              f"({'FINAL CALL' if final else 'regular'}). Preview: {eml}\n"
              f"Subject: {subject}\n"
              f"------------------------------------------------------------\n"
              f"{body}\n"
              f"------------------------------------------------------------\n"
              f"To: {', '.join(RECIPIENTS)}", flush=True)
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
          f"{len(RECIPIENTS)} recipient(s).", flush=True)
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
