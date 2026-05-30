"""Email the full-captainship Scheduled 6 days out PNG to each team.

Sends from alphaletereporting@gmail.com over Gmail SMTP (SSL, port 465) using a
Gmail **App Password** — NOT the account's normal password. The app password is
read from a gitignored file (or env var), never hardcoded:

  ~/.config/recruiting-report/gmail-app-password   (one line, the 16-char pwd)
  or env var  ALPHALETE_REPORTING_GMAIL_APP_PASSWORD

The app password needs 2-Step Verification enabled on alphaletereporting@ and is
generated at myaccount.google.com → Security → App passwords. That file lives
OUTSIDE the repo and is never committed.

Recipient lists live here in code (Eve manages them directly). The signature is
appended in the body (Gmail's web-UI signature does NOT apply to programmatic
sends, so we build it ourselves).
"""
from __future__ import annotations

import os
import smtplib
import ssl
import tempfile
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Optional

FROM_ADDR = "alphaletereporting@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

_APP_PW_FILE = Path.home() / ".config" / "recruiting-report" / "gmail-app-password"
_APP_PW_ENV = "ALPHALETE_REPORTING_GMAIL_APP_PASSWORD"

# Recipient lists per captainship. Eve edits these directly when a group member
# changes — no Gmail contact-group resolution (programmatic sends can't expand a
# Gmail group name; they need explicit addresses).
RECIPIENTS: dict[str, List[str]] = {
    "raf": [
        "andrew.sanborn07@gmail.com", "Anthony64martinez@gmail.com",
        "Ayakhafaji02@gmail.com", "Benjaminburden02@gmail.com",
        "carissang46@gmail.com", "codycannon1993@gmail.com",
        "cywadeambient@gmail.com", "dylanjtwaddle@gmail.com",
        "edgarmuniz2020@icloud.com", "ericdmartinez222@gmail.com",
        "orbitc2025@gmail.com", "m.hammad.malikk@gmail.com",
        "haythamnagi1@gmail.com", "Jacoblmorgan23@gmail.com",
        "jenniferfigueroa55@gmail.com", "youngjohnrichard@gmail.com",
        "Loganjoseph81@yahoo.com", "Palace.kash@gmail.com",
        "kiarri.mcbroom@gmail.com", "kimberlyatt458@gmail.com",
        "marcellusbutlerjr@gmail.com", "marcial.enrique@yahoo.com",
        "maudmiller4@gmail.com", "melikeljaiez@yahoo.com",
        "Zenithzenith2099@gmail.com", "nataliagwarda@gmail.com",
        "nweldon0130@gmail.com", "niitagoe4@gmail.com", "raffi127@gmail.com",
        "salikmallick6@gmail.com", "samjpark1497@gmail.com",
        "sharonstephen2222@gmail.com", "mcelwee.steve95@gmail.com",
        "tonycv1920@gmail.com", "trang.lecanavan@gmail.com",
        "tre.mitchell60@gmail.com", "kesslerzadrian@gmail.com",
    ],
    "starr": [
        "dylanjtwaddle@gmail.com", "jason.vyzahinc@gmail.com",
        "jpascual@elevaremanagementinc.com", "maudmiller4@gmail.com",
        "milly.vinceremarketing@gmail.com", "omniamanagementinc@gmail.com",
        "raffi127@gmail.com", "starr.novamanagement@gmail.com",
        "William@optimabusinessmgmt.com",
    ],
}

# Eve's signature is an IMAGE (her branded sig with photo), embedded inline in
# the body after "Best,". Lives in the package so the report doesn't depend on a
# file in Downloads. Gmail's stored signature doesn't apply over SMTP, so we
# embed it ourselves. Displayed at SIGNATURE_WIDTH px (native 445px) — sized to
# sit proportionally under the table, not dominate it.
SIGNATURE_IMG = Path(__file__).resolve().parent / "assets" / "signature.png"
SIGNATURE_WIDTH = 420

# Plain-text fallback only (clients that don't render HTML/images).
_SIGNATURE_TEXT = (
    "Best,\n\n"
    "Evelyn Sobrino\n"
    "Virtual Assistant, Alphalete Marketing\n"
    "alphaletereporting@gmail.com"
)


class EmailSendError(RuntimeError):
    pass


def app_password() -> str:
    """Read the Gmail app password from env or the gitignored file. Spaces (the
    way Google displays the 16-char password, in 4 groups) are stripped."""
    raw = os.environ.get(_APP_PW_ENV, "")
    if not raw and _APP_PW_FILE.exists():
        raw = _APP_PW_FILE.read_text(encoding="utf-8-sig")
    pw = "".join(raw.split())  # drop all whitespace, incl the display spaces
    if not pw:
        raise EmailSendError(
            f"No Gmail app password found. Save it to {_APP_PW_FILE} (one line) "
            f"or set {_APP_PW_ENV}. It must be an App Password for {FROM_ADDR} "
            "(needs 2-Step Verification on that account). Never commit it."
        )
    return pw


def build_message(subject: str, png_path: Path,
                  to_addrs: List[str]) -> EmailMessage:
    """Build an HTML email with the captainship PNG inline in the body, then
    'Best,' and Eve's signature IMAGE. Both images are embedded inline (CID).
    A plain-text alternative is included for clients that can't render HTML."""
    if not SIGNATURE_IMG.exists():
        raise EmailSendError(
            f"Signature image not found at {SIGNATURE_IMG}. Put Eve's signature "
            "PNG there (see assets/).")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)

    msg.set_content(
        "This report is best viewed in an HTML email client.\n\n"
        + _SIGNATURE_TEXT
    )

    cid_report = make_msgid()   # includes angle brackets
    cid_sig = make_msgid()
    html = (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
        "color:#000\">"
        f'<img src="cid:{cid_report[1:-1]}" '
        'style="max-width:100%;border:1px solid #ddd"/><br><br>'
        "Best,<br><br>"
        f'<img src="cid:{cid_sig[1:-1]}" width="{SIGNATURE_WIDTH}" '
        'style="max-width:100%;height:auto"/>'
        "</div>"
    )
    msg.add_alternative(html, subtype="html")

    html_part = msg.get_payload()[1]
    html_part.add_related(png_path.read_bytes(),
                          maintype="image", subtype="png", cid=cid_report)
    html_part.add_related(SIGNATURE_IMG.read_bytes(),
                          maintype="image", subtype="png", cid=cid_sig)
    return msg


def send(team: str, png_path: Path, subject: str,
         dry_run: bool = False, test_to: Optional[str] = None) -> dict:
    """Send the team's email.

    dry_run: build the message, write it to a .eml for inspection, and DON'T
             send (returns the recipient list + subject).
    test_to: send for real but ONLY to this single address (safe live test
             before blasting the whole group).
    """
    team = team.lower()
    if team not in RECIPIENTS:
        raise EmailSendError(f"Unknown team {team!r} (expected raf/starr).")
    to_addrs = [test_to] if test_to else list(RECIPIENTS[team])

    msg = build_message(subject, png_path, to_addrs)

    if dry_run:
        eml = Path(tempfile.gettempdir()) / f"scheduled_6days_{team}.eml"
        eml.write_bytes(bytes(msg))
        return {"dry_run": True, "team": team, "subject": subject,
                "to_count": len(to_addrs), "to": to_addrs, "eml": str(eml)}

    pw = app_password()
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
            s.login(FROM_ADDR, pw)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise EmailSendError(
            "Gmail rejected the login. Check that the app password is correct "
            f"and 2-Step Verification is on for {FROM_ADDR}. ({e})") from e
    return {"sent": True, "team": team, "subject": subject,
            "to_count": len(to_addrs), "to_sample": to_addrs[:3]}
