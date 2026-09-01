"""The email leg of the KNOCKS & DISPOSITIONS board.

Question 3 on Raf's sign-up ("email or iMessage text, or both") is the reason
this exists: iMessage was the only route until offices started enrolling
themselves, and an owner who wants it in their inbox is not asking for a
different report.

ONE SENDER for the whole repo — org_sales_board.screenshot_email.send, from
alphaletereporting@ over Gmail SMTP, the same address every other report mails
from. Nothing is rendered here: the boards this attaches are the exact images
that just went to Messages, so an owner comparing the two is looking at one
picture.

Python 3.9-safe. Never raises on a send failure that the caller can survive —
the caller logs it and keeps the other routes.
"""
from __future__ import annotations

import datetime as dt
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List

from automations.gap_alerts import config as C


def subject_for(cfg: Dict, slot: str, day: dt.date) -> str:
    who = (cfg.get("label") or cfg.get("name") or "").strip()
    camp = (cfg.get("campaign_label") or "").strip()
    bits = [C.CARD_TITLE.title()]
    if who:
        bits.append(who)
    if camp:
        bits.append(camp)
    # The clock, not just the date: these arrive up to four times an hour and
    # an inbox showing four identical subjects is an inbox nobody opens.
    return "%s — %d/%d, %s" % (" — ".join(bits), day.month, day.day, slot)


def build(cfg: Dict, boards: "List[Path]", body: str, slot: str,
          day: dt.date, to_addrs: "List[str]") -> EmailMessage:
    """The message, boards attached. `body` is the gap list (may be empty —
    an empty gap list is good news and the board still carries the day)."""
    from automations.scheduled_6_days_out.email_send import FROM_ADDR

    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject_for(cfg, slot, day)
    text = body.strip() or "No reps over %d minutes right now." % C.GAP_THRESHOLD_MIN
    msg.set_content("%s\n\n(Board attached — as of %s.)\n" % (text, slot))
    for p in boards:
        p = Path(p)
        try:
            data = p.read_bytes()
        except OSError:
            continue
        sub = "pdf" if p.suffix.lower() == ".pdf" else "png"
        main = "application" if sub == "pdf" else "image"
        msg.add_attachment(data, maintype=main, subtype=sub, filename=p.name)
    return msg


def send(cfg: Dict, boards: "List[Path]", body: str, slot: str, day: dt.date,
         *, dry_run: bool = True) -> Dict:
    """Mail this office's board to its enrolled addresses. Returns a small dict
    for the log line; raises only on a real SMTP failure so the caller can
    record it as a route failure without losing the others."""
    to_addrs = [a for a in (cfg.get("email_to") or []) if a]
    if not to_addrs:
        return {"skipped": "no email_to", "to": []}
    msg = build(cfg, boards, body, slot, day, to_addrs)
    if dry_run:
        return {"dry_run": True, "to": to_addrs, "subject": msg["Subject"],
                "attachments": [Path(p).name for p in boards]}
    from automations.org_sales_board.screenshot_email import send as _smtp_send
    _smtp_send(msg)
    return {"to": to_addrs, "subject": msg["Subject"], "ok": True}
