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
import html as _html
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional, Tuple

from automations.captainship_drafts.config import Captain
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, PHOTO_EMBED_PX, PHOTO_IMG,
    _signature_html, _circular_photo_png,
)

_FONT_STACK = "Arial,Helvetica,sans-serif"

# The sentence every 'pending' note carries. It is a CONSTANT because the send
# path greps for it: run.py --send-reviewed refuses to mail a report that still
# shows one. Change the wording here and the guard follows; inline it back into
# the f-string and the guard silently stops matching.
PENDING_MARK = "could not be captured on this run"


def _intro_html(captain: Captain) -> str:
    greeting, items = captain.intro
    lis = "".join(f"<li>{it}</li>" for it in items)
    return (f'<div style="font-size:14px">{greeting}</div>'
            f'<ol style="font-size:14px;margin:6px 0 16px 0">{lis}</ol>')


def _pending(what: str, why: str = "") -> str:
    """The honest 'this section has no image' note.

    `why` is the exception the capture died on, carried through the bundle's
    'errors' map. Without it the note is unactionable: the reason only ever
    existed as one line in the run's log, on whichever machine built the draft,
    so Eve reading the report had no way to tell a Tableau session that expired
    from a captain whose Sales Board header got renamed. Printed small and last
    so the section still reads as a status note, not a stack trace."""
    reason = (f'<div style="font-size:11px;color:#7a5600;margin-top:4px">'
              f'{_html.escape(why)}</div>') if why else ""
    return (f'<div style="font-size:12px;color:#9a6b00;background:#fff4d6;'
            f'border:1px solid #f0d271;border-radius:4px;padding:8px 10px;'
            f'margin:4px 0 10px">— {what} {PENDING_MARK} '
            f'(re-run after fixing the source) —{reason}</div>')


def _not_available(what: str) -> str:
    """For a section whose SOURCE DOES NOT EXIST YET — a known, accepted state,
    not a failure.

    Deliberately does NOT carry PENDING_MARK, so run.py --send-reviewed will
    mail the report instead of holding it. That distinction is the whole point:
    'the capture broke, go fix it' must block a send, but 'nobody has built this
    source yet' must not hold a captain's report hostage indefinitely.

    Atef's captainship (2026-08-18) is the case that needed it: his §2 comes off
    a Tableau team filter that only SmartCircle can create, so his report could
    not be mailed at all while the note read like a fixable error
    [[project_atef-captainship-waiting-on-smartcircle]]."""
    return (f'<div style="font-size:12px;color:#555;background:#f4f4f4;'
            f'border:1px solid #ddd;border-radius:4px;padding:8px 10px;'
            f'margin:4px 0 10px">{what}: Not available yet.</div>')


def _slug_slot(s: str) -> str:
    """Content-ID / filename safe: lowercase alnum + single dashes."""
    out = "".join(c if c.isalnum() else "-" for c in s.lower())
    return "-".join(p for p in out.split("-") if p) or "img"


class _Images:
    """Collects (cid, path, filename) as blocks are built, so add_related runs
    once.

    Content-IDs are SHORT and SEMANTIC ("03-churn-ni-1@captainship.report"),
    never make_msgid(). This is not cosmetic — it's the 2026-07-27 fix for
    Eve's "the images swapped places and got mixed up, even in the mails
    already sent":

      make_msgid() emits <centisecond.pid.random64@THIS-HOSTNAME>, so every
      image in one mail shared a ~14-char prefix (same centisecond, same pid)
      and a machine-name domain, differing only in the random tail. What WE
      generate is always correct (verified: unique cids, HTML order == MIME
      order, every captain, every batch) — but when a draft is opened in the
      Gmail web UI, Gmail hoists the inline images into its own attachment
      store and re-anchors each <img> to an attachment. On those near-identical
      cids that re-anchor collided: Luis' 7/26 draft came back with its images
      bound in the order 1,2,7,5,8,4,3,6, with one cid used TWICE (so one
      chart rendered twice and another vanished). Sending the draft bakes the
      scramble in, which is why already-sent mail was wrong too.

    Gmail reorders the parts either way — that is NOT the bug and can't be
    stopped. The goal is only that every cid survives a reorder, which distinct
    Content-IDs achieve on their own. Naming the parts was tried as a "second
    half" of the fix and had to be reverted: see the warning in build()."""

    _DOMAIN = "captainship.report"

    def __init__(self) -> None:
        self.pairs: List[Tuple[str, Path, str]] = []

    def img(self, path, *, slot: str, caption: Optional[str] = None) -> str:
        # The NN- prefix is what guarantees uniqueness (a slot name could
        # legitimately repeat); the slot name is what makes it unambiguous.
        token = f"{len(self.pairs) + 1:02d}-{_slug_slot(slot)}"
        cid = f"<{token}@{self._DOMAIN}>"
        self.pairs.append((cid, Path(path), f"{token}.png"))
        cap = (f'<div style="font-size:13px;font-weight:bold;margin:12px 0 4px">'
               f'{caption}</div>' if caption else "")
        # display:block so consecutive images STACK vertically (one per row).
        # Without it the inline <img> boxes flow side-by-side into a grid when
        # they're narrow enough — churn buckets must read top-to-bottom.
        return (cap + f'<img src="cid:{cid[1:-1]}" '
                f'style="display:block;max-width:100%;border:1px solid #ddd"/>')


def _teamstats_configured(captain) -> bool:
    """Is a §2 source wired for this captain at all? Asked of tableau_shot
    itself, so the two can never drift apart."""
    try:
        from automations.captainship_drafts import tableau_shot
        return tableau_shot._spec_for(captain.key, captain.flavor) is not None
    except Exception:  # noqa: BLE001 — an import/lookup problem is NOT proof
        return True     # that the source is unconfigured; fall back to pending



def _section_html(captain: Captain, heading: str, kind: str, n: int,
                  bundle: dict, imgs: _Images) -> str:
    head = (f'<div style="font-size:16px;font-weight:bold;margin:18px 0 6px">'
            f'{n}. {heading}</div>')
    # Why this section's capture failed, keyed by bundle key — run.py fills it
    # as it catches each failure. Absent key = no recorded reason.
    err = bundle.get("errors") or {}
    body = ""
    if kind == "product_summary":
        ps = bundle.get("product_summary")
        body += (imgs.img(ps, slot="product-summary") if ps
                 else _pending("Product Summary screenshot",
                               err.get("product_summary", "")))
        units = bundle.get("units") or []
        body += ('<div style="font-size:14px;font-weight:bold;margin:14px 0 4px">'
                 'CAPTAINSHIP UNITS:</div>')
        if units:
            for i, (caption, path) in enumerate(units):
                body += imgs.img(path, slot=f"units-{i}", caption=caption)
        else:
            # Same capture as the Product Summary above, so it fails for the
            # same reason — reuse it rather than leave this half bare.
            body += _pending("Captainship Units screenshot",
                             err.get("units") or err.get("product_summary", ""))
    elif kind == "fiber_activation":
        fa = bundle.get("fiber_activation")
        body += (imgs.img(fa, slot="fiber-activations") if fa
                 else _pending("Fiber Activations PNG",
                               err.get("fiber_activation", "")))
    elif kind == "cancel_tableau":
        ct = bundle.get("cancel_tableau")
        body += (imgs.img(ct, slot="cancel-rates") if ct
                 else _pending("Cancel-Rates Tableau shot",
                               err.get("cancel_tableau", "")))
    elif kind == "teamstats_tableau":
        ts = bundle.get("teamstats_tableau")
        if ts:
            body += imgs.img(ts, slot="team-stats")
        elif not _teamstats_configured(captain):
            # No source wired for this captain yet — say so plainly and let the
            # rest of the report go out. See _not_available.
            body += _not_available("Captain Team Stats Breakout")
        else:
            body += _pending("Team Stats Breakout Tableau shot",
                             err.get("teamstats_tableau", ""))
    elif kind.startswith("box:"):
        # One-column-per-day metrics box (cancel / activation / ABP / 6-days).
        slot = kind.split(":", 1)[1]
        path = (bundle.get("boxes") or {}).get(slot)
        body += (imgs.img(path, slot=slot) if path
                 else _pending(f"{heading} box",
                               err.get(f"box:{slot}") or err.get("boxes", "")))
    elif kind in ("churn_ni", "churn_wireless"):
        items = bundle.get(kind) or []
        if items:
            for i, (_caption, path) in enumerate(items):
                body += imgs.img(path, slot=f"{kind.replace('_', '-')}-{i}")
        else:
            body += _pending("churn images", err.get(kind, ""))
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
    churn_ni([(cap,Path)]), churn_wireless([(cap,Path)]),
    boxes({slot: Path}), errors({bundle key: reason}).  Missing keys render as
    a per-section 'pending' note, carrying that key's reason when there is
    one."""
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

    # Same short/semantic scheme as the section images (see _Images) — the
    # signature photo is just the last part in the same related bundle.
    cid_photo = f"<{len(imgs.pairs) + 1:02d}-signature@{_Images._DOMAIN}>"
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
    # NEVER pass filename= here, and never set a disposition by hand. Tried it
    # on 2026-07-27 and it silently broke SENDING: a named part reads to Gmail
    # as a real file attachment, so its draft rewrite moved all 9 images out of
    # multipart/related into a multipart/mixed as "attachment". The compose
    # window still looked right (Gmail renders those from its own store), but
    # the mail that went out had cid: refs pointing at parts no longer inside
    # the related container — Eve got the body text and nine broken images.
    # Bare add_related (inline, unnamed) is what Gmail keeps as a real inline
    # image. The scramble this module exists to fix is cured by the Content-IDs
    # above, not by naming the parts.
    for cid, path, _filename in imgs.pairs:
        html_part.add_related(Path(path).read_bytes(),
                              maintype="image", subtype="png", cid=cid)
    html_part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                          maintype="image", subtype="png", cid=cid_photo)
    return msg
