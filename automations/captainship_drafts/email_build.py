"""Assemble a Captainship Report draft as an email.message.EmailMessage.

PHASE 1: intro + the churn section (inline images) + Eve's HTML signature
(reused verbatim from scheduled_6_days_out.email_send). Sections 1
(Product Summary) and 2 (Cancel / Captain Team Stats Breakout) are shown
as a clearly-labeled "pending" placeholder so a preview isn't mistaken
for the finished email; they get wired in later phases.

The message is handed to automations.shared.gmail_draft.create_draft —
nothing is sent. 'To' is intentionally left blank (Eve fills it before
sending, per the agreed flow)."""
from __future__ import annotations

import datetime as dt
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Tuple

from automations.captainship_drafts.config import Captain
# Reuse Eve's HTML signature + photo embedding from the 6-days report.
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, PHOTO_EMBED_PX, PHOTO_IMG,
    _signature_html, _circular_photo_png,
)

_FONT_STACK = "Arial,Helvetica,sans-serif"
# Section numbers whose content is not built yet (Phase 1 = churn only).
_PENDING_SECTIONS = (1, 2)


def _intro_html(captain: Captain) -> str:
    greeting, items = captain.intro
    lis = "".join(f"<li>{it}</li>" for it in items)
    return (f'<div style="font-size:14px">{greeting}</div>'
            f'<ol style="font-size:14px;margin:6px 0 16px 0">{lis}</ol>')


def _pending_banner() -> str:
    nums = " & ".join(str(n) for n in _PENDING_SECTIONS)
    return (f'<div style="font-size:12px;color:#9a6b00;background:#fff4d6;'
            f'border:1px solid #f0d271;border-radius:4px;padding:8px 10px;'
            f'margin-bottom:16px">PREVIEW — sections {nums} (Product Summary, '
            f'Cancel / Team Stats) are not built yet. This draft shows the '
            f'churn section only.</div>')


def build(captain: Captain, churn_images: List[Tuple[str, "Path"]],
          today: dt.date) -> EmailMessage:
    """Build the draft message for `captain` with its churn images inline."""
    msg = EmailMessage()
    msg["Subject"] = f"{captain.display_name}'s Captainship Report " \
                     f"({today.month}/{today.day})"
    msg["From"] = FROM_ADDR
    msg["To"] = ""   # blank on purpose — reviewer fills before sending

    msg.set_content(
        "This Captainship Report is best viewed in an HTML email client.\n\n"
        "Kind regards,\nEve")

    # Build inline image blocks (caption above each PNG), collecting CIDs.
    cid_for_path: list = []
    img_blocks: list[str] = []
    for caption, path in churn_images:
        cid = make_msgid()
        cid_for_path.append((cid, path))
        img_blocks.append(
            f'<div style="font-size:13px;font-weight:bold;margin:14px 0 4px">'
            f'{caption}</div>'
            f'<img src="cid:{cid[1:-1]}" '
            f'style="max-width:100%;border:1px solid #ddd"/>')

    cid_photo = make_msgid()
    churn_heading = ("💰New Internet / Wireless Ongoing Churn Metrics 💰"
                     if captain.flavor == "rafael"
                     else "💰New Internet Ongoing Churn Metrics 💰")

    html = (
        f'<div style="font-family:{_FONT_STACK};color:#000">'
        f'{_intro_html(captain)}'
        f'{_pending_banner()}'
        f'<div style="font-size:16px;font-weight:bold;margin:8px 0">'
        f'{churn_heading}</div>'
        f'{"".join(img_blocks)}'
        '<br>Kind regards,<br><br>'
        f'{_signature_html(cid_photo)}'
        '</div>'
    )
    msg.add_alternative(html, subtype="html")

    html_part = msg.get_payload()[1]
    for cid, path in cid_for_path:
        html_part.add_related(Path(path).read_bytes(),
                              maintype="image", subtype="png", cid=cid)
    html_part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                          maintype="image", subtype="png", cid=cid_photo)
    return msg
