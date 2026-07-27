"""Assemble a Captainship Report draft as an email.message.EmailMessage.

Builds the full body per flavor from an image bundle, in the section order
the spec lays out (config.SECTION_KINDS):

  §1 Product Summary  -> the Sales Board PS screenshot, then a
                         "CAPTAINSHIP UNITS:" sub-heading + the unit delta
                         charts (fiber: New Internet + All Units).
  fiber §2            -> the daily Fiber Activations PNG.
  §2 (Rafael/fiber)   -> Tableau Cancel-Rates shot (filtered to the team).
  §2 (B2B/NDS)        -> Tableau Captain Team Stats Breakout shot.
  churn §§            -> the rendered churn bucket images (self-titled).

Any section whose image the caller couldn't produce yet (today: the Tableau
§2 shots) shows a small honest "pending" note IN THAT SECTION only, so a
preview is never mistaken for the finished email.

The message goes to automations.shared.gmail_draft.create_draft — nothing is
sent. 'To' is left blank (Eve fills it before sending, per the agreed flow).
Signature reused verbatim from scheduled_6_days_out.email_send.
"""
from __future__ import annotations

import datetime as dt
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Optional, Tuple

from automations.captainship_drafts.config import Captain
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, PHOTO_EMBED_PX, PHOTO_IMG,
    _signature_html, _circular_photo_png,
)

_FONT_STACK = "Arial,Helvetica,sans-serif"


def _intro_html(captain: Captain) -> str:
    greeting, items = captain.intro
    lis = "".join(f"<li>{it}</li>" for it in items)
    return (f'<div style="font-size:14px">{greeting}</div>'
            f'<ol style="font-size:14px;margin:6px 0 16px 0">{lis}</ol>')


def _pending(what: str) -> str:
    return (f'<div style="font-size:12px;color:#9a6b00;background:#fff4d6;'
            f'border:1px solid #f0d271;border-radius:4px;padding:8px 10px;'
            f'margin:4px 0 10px">— {what} could not be captured on this run '
            f'(re-run after fixing the source) —</div>')


class _Images:
    """Collects (cid, path) as blocks are built, so add_related runs once."""
    def __init__(self) -> None:
        self.pairs: List[Tuple[str, Path]] = []

    def img(self, path, *, caption: Optional[str] = None) -> str:
        cid = make_msgid()
        self.pairs.append((cid, Path(path)))
        cap = (f'<div style="font-size:13px;font-weight:bold;margin:12px 0 4px">'
               f'{caption}</div>' if caption else "")
        # display:block so consecutive images STACK vertically (one per row).
        # Without it the inline <img> boxes flow side-by-side into a grid when
        # they're narrow enough — churn buckets must read top-to-bottom.
        return (cap + f'<img src="cid:{cid[1:-1]}" '
                f'style="display:block;max-width:100%;border:1px solid #ddd"/>')


def _section_html(captain: Captain, heading: str, kind: str, n: int,
                  bundle: dict, imgs: _Images) -> str:
    head = (f'<div style="font-size:16px;font-weight:bold;margin:18px 0 6px">'
            f'{n}. {heading}</div>')
    body = ""
    if kind == "product_summary":
        ps = bundle.get("product_summary")
        body += imgs.img(ps) if ps else _pending("Product Summary screenshot")
        units = bundle.get("units") or []
        body += ('<div style="font-size:14px;font-weight:bold;margin:14px 0 4px">'
                 'CAPTAINSHIP UNITS:</div>')
        if units:
            for caption, path in units:
                body += imgs.img(path, caption=caption)
        else:
            body += _pending("Captainship Units screenshot")
    elif kind == "fiber_activation":
        fa = bundle.get("fiber_activation")
        body += imgs.img(fa) if fa else _pending("Fiber Activations PNG")
    elif kind == "cancel_tableau":
        ct = bundle.get("cancel_tableau")
        body += imgs.img(ct) if ct else _pending("Cancel-Rates Tableau shot")
    elif kind == "teamstats_tableau":
        ts = bundle.get("teamstats_tableau")
        body += imgs.img(ts) if ts else _pending("Team Stats Breakout Tableau shot")
    elif kind in ("churn_ni", "churn_wireless"):
        items = bundle.get(kind) or []
        if items:
            for _caption, path in items:
                body += imgs.img(path)
        else:
            body += _pending("churn images")
    return head + body


def subject_prefix(captain: Captain) -> str:
    """The captain-identifying, date-free part of the subject.

    Possessive: names ending in 's' take a bare apostrophe (spec:
    "Carlos'", "Luis'"); everyone else takes "'s" ("Wayne's", "Eveliz's")."""
    name = captain.display_name
    poss = f"{name}'" if name.endswith("s") else f"{name}'s"
    return f"{poss} Captainship Report"


def reported_date(today: dt.date) -> dt.date:
    """The day the report COVERS, given the day it RUNS on — the day before.

    Every section of this draft is anchored to the prior day: the Captainship
    Units chart shows `prior_day_columns` (today-1), and the churn + fiber
    activation images read that same day's column. So a Monday run reports
    SUNDAY, and per Eve (2026-07-27) the subject must name the day reported,
    not the day it ran.

    Keep the run date as the argument everywhere and derive this — collapsing
    the two back into one variable is what caused the 7/26 batch: passing
    `--date 2026-07-26` to make the subject read 7/26 silently walked every
    section back to SATURDAY."""
    return today - dt.timedelta(days=1)


def subject_for(captain: Captain, today: dt.date) -> str:
    """The exact Subject header build() sets, for a run on `today`. Single
    source of truth — the idempotency sweep in run.py matches against this, so
    a subject format change can never silently stop matching the drafts it
    should replace."""
    d = reported_date(today)
    return f"{subject_prefix(captain)} {d.month}/{d.day}"


def build(captain: Captain, bundle: dict, today: dt.date) -> EmailMessage:
    """Build the draft message for `captain` from its image `bundle`.

    bundle keys: product_summary(Path), units([(cap,Path)]),
    fiber_activation(Path), cancel_tableau(Path), teamstats_tableau(Path),
    churn_ni([(cap,Path)]), churn_wireless([(cap,Path)]).  Missing keys
    render as a per-section 'pending' note."""
    msg = EmailMessage()
    msg["Subject"] = subject_for(captain, today)
    msg["From"] = FROM_ADDR
    msg["To"] = ""   # blank on purpose — reviewer fills before sending

    msg.set_content(
        "This Captainship Report is best viewed in an HTML email client.\n\n"
        "Kind regards,\nEve")

    imgs = _Images()
    sections_html = "".join(
        _section_html(captain, heading, kind, n, bundle, imgs)
        for n, (heading, kind) in enumerate(captain.sections, 1))

    cid_photo = make_msgid()
    html = (
        f'<div style="font-family:{_FONT_STACK};color:#000">'
        f'{_intro_html(captain)}'
        f'{sections_html}'
        '<br>Kind regards,<br><br>'
        f'{_signature_html(cid_photo)}'
        '</div>'
    )
    msg.add_alternative(html, subtype="html")

    html_part = msg.get_payload()[1]
    for cid, path in imgs.pairs:
        html_part.add_related(Path(path).read_bytes(),
                              maintype="image", subtype="png", cid=cid)
    html_part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                          maintype="image", subtype="png", cid=cid_photo)
    return msg
