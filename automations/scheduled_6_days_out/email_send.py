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

import io
import os
import smtplib
import ssl
import tempfile
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw

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

# Eve's signature is BUILT here: her photo (circular) on the left + text on the
# right. We build it instead of using Gmail's stored signature because that only
# applies when composing in the web UI, not over SMTP. The photo lives in the
# package so the report doesn't depend on a file in Downloads.
PHOTO_IMG = Path(__file__).resolve().parent / "assets" / "eve_photo.png"
PHOTO_DISPLAY_PX = 84    # rendered size in the email
PHOTO_EMBED_PX = 200     # embedded resolution (crisp on retina, small file)

_SIG_NAME = "Evelyn Sobrino"
_SIG_TITLE = "Virtual Assistant, Alphalete Marketing"
_SIG_EMAIL = "alphaletereporting@gmail.com"

# Plain-text fallback only (clients that don't render HTML/images).
_SIGNATURE_TEXT = (
    "Best,\n\n"
    f"{_SIG_NAME}\n{_SIG_TITLE}\n{_SIG_EMAIL}"
)


def _circular_photo_png(path: Path, px: int) -> bytes:
    """Resize `path` to px×px and crop to a circle (transparent corners), so the
    photo renders round in every client — not just ones that honor CSS
    border-radius. Returns PNG bytes."""
    im = Image.open(path).convert("RGBA").resize((px, px), Image.LANCZOS)
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px, px), fill=255)
    im.putalpha(mask)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _signature_html(cid_photo: str) -> str:
    """Photo (left) + name/title/email (right), as an email-safe table."""
    d = PHOTO_DISPLAY_PX
    return (
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="middle"><img src="cid:{cid_photo[1:-1]}" width="{d}" '
        f'height="{d}" style="display:block;border-radius:50%"/></td>'
        '<td valign="middle" style="padding-left:14px;'
        'font-family:Arial,Helvetica,sans-serif">'
        f'<div style="font-size:16px;font-weight:bold;color:#000">{_SIG_NAME}</div>'
        f'<div style="font-size:13px;color:#555">{_SIG_TITLE}</div>'
        f'<div style="font-size:13px"><a href="mailto:{_SIG_EMAIL}" '
        f'style="color:#1a73e8;text-decoration:none">{_SIG_EMAIL}</a></div>'
        '</td></tr></table>'
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
    'Best,' and Eve's signature (circular photo + text). Both images are
    embedded inline (CID). A plain-text alternative is included for clients
    that can't render HTML."""
    if not PHOTO_IMG.exists():
        raise EmailSendError(
            f"Signature photo not found at {PHOTO_IMG}. Put Eve's photo there "
            "(see assets/eve_photo.png).")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)

    msg.set_content(
        "This report is best viewed in an HTML email client.\n\n"
        + _SIGNATURE_TEXT
    )

    cid_report = make_msgid()   # includes angle brackets
    cid_photo = make_msgid()
    html = (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
        "color:#000\">"
        f'<img src="cid:{cid_report[1:-1]}" '
        'style="max-width:100%;border:1px solid #ddd"/><br><br>'
        "Best,<br><br>"
        f"{_signature_html(cid_photo)}"
        "</div>"
    )
    msg.add_alternative(html, subtype="html")

    html_part = msg.get_payload()[1]
    html_part.add_related(png_path.read_bytes(),
                          maintype="image", subtype="png", cid=cid_report)
    html_part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                          maintype="image", subtype="png", cid=cid_photo)
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
