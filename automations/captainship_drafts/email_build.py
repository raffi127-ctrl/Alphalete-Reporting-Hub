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

from automations.shared import board_email_html as _beh

# Tighter than the shared default (2 x WRAPPER_PX) because of what THIS message
# carries: on Sun/Mon both knock sections are inline, ~34 board images, plus the
# weekly PDF. Measured 2026-08-30 at 2x render scale, the shared cap put the
# message near 28MB base64 — past Gmail's 25MB, where it FAILS to send rather
# than arriving degraded. 1800 lands the whole thing near 20MB and is still
# wider than the boards were drawn before 2x, so nothing a reader could zoom
# into has been taken away.
_INLINE_PX = 1800

# HOW BIG THE WHOLE MESSAGE MAY GET, and why the number is on the MESSAGE and
# not on the attachments. Gmail refuses anything over 25MB — it FAILS the send
# rather than delivering a degraded copy — so a report that grows past the line
# does not arrive smaller, it does not arrive.
#
# EVERY PAGE STAYS AT THE STANDARD WIDTH (Eve, 2026-09-01: "el ancho de pixeles
# tiene que ser igual para todos, por algo se llevo a una medida estandar, y lo
# mas importante: LEGIBLE"). Shrinking one report's pages to buy room was tried
# and reverted the same day: a board nobody can read is not a smaller report,
# it is a lost one. So legibility is fixed and the SIZE is what adapts.
#
# Measured 2026-09-01 on Rafael's, the biggest captainship: 22.8MB with all 15
# attachments — it fits, and every owner keeps their page. A budget guessed
# against the attachments alone sat 0.3MB from trimming him on a normal day,
# which is why this is measured on the assembled message instead: the per-owner
# copies are added while the real byte count stays under the cap, so nothing is
# ever dropped for a size the message did not actually reach.
MAX_MESSAGE_BYTES = 24 * 1024 * 1024
from automations.captainship_drafts.config import Captain
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, PHOTO_EMBED_PX, PHOTO_IMG,
    _signature_html, _circular_photo_png, _SIGNATURE_TEXT_BODY,
)

_FONT_STACK = "Arial,Helvetica,sans-serif"

# The sentence every 'pending' note carries. It is a CONSTANT because the send
# path greps for it: run.py --send-reviewed refuses to mail a report that still
# shows one. Change the wording here and the guard follows; inline it back into
# the f-string and the guard silently stops matching.
PENDING_MARK = "could not be captured on this run"

# The other half of that contract: a source that ANSWERED and had nothing to
# show. A capture prefixes its reason with this and the note flips from the
# yellow "go fix the source" box to a grey "no data available" one that does
# NOT carry PENDING_MARK — so a genuine zero neither reads as a failure nor
# holds the report back at run.py's send guard.
#
# Eve 2026-08-24: Sunday's Daily Knocks came back empty for four of Rafael's
# ICDs — nobody knocked — and the report told her the board "could not be
# captured (re-run after fixing the source)". Ten of the day's forty-four
# notes were real zeros wearing a failure's clothes.
NO_DATA_MARK = "no-data::"


# A one-off line rendered ABOVE the greeting, set from `run.py --note` (Eve
# 2026-09-03). It exists for the day a draft is rebuilt AFTER its first version
# already reached the captains: without it they get two mails and no way to tell
# which one to read. Empty (the default) renders nothing at all, so the normal
# daily build is byte-identical to before.
NOTICE = ""


def _notice_html() -> str:
    if not NOTICE.strip():
        return ""
    return ('<div style="font-size:14px;font-weight:bold;margin:0 0 12px 0">'
            f'{_html.escape(NOTICE.strip())}</div>')


def _intro_html(captain: Captain, today: dt.date) -> str:
    """The greeting + numbered list of TODAY'S sections. The items come from
    sections_on(today), not the full flavor list — a day-gated section (the
    Sun/Mon-only Weekly Knock Dispositions) must vanish from the intro too,
    or the list promises a section the body below doesn't carry. Since each
    intro item IS its section's heading (config zips them), filtering the
    sections filters the bullets for free and the two can't drift."""
    greeting, _items = captain.intro
    lis = "".join(f"<li>{h}</li>"
                  for h, _k in captain.body_sections_on(today))
    return (f'<div style="font-size:14px">{greeting}</div>'
            f'<ol style="font-size:14px;margin:6px 0 16px 0">{lis}</ol>')


def _pending(what: str, why: str = "") -> str:
    """The honest 'this section has no image' note.

    `why` is the exception the capture died on, carried through the bundle's
    'errors' map. Without it the note is unactionable: the reason only ever
    existed as one line in the run's log, on whichever machine built the draft,
    so Eve reading the report had no way to tell a Tableau session that expired
    from a captain whose Sales Board header got renamed. Printed small and last
    so the section still reads as a status note, not a stack trace.

    A `why` prefixed with NO_DATA_MARK means the source answered and had
    nothing — that is not a pending capture, so it renders as _no_data()
    instead. Routed HERE, in the one function every section already calls, so
    no caller has to remember the distinction."""
    if why.startswith(NO_DATA_MARK):
        return _no_data(what, why[len(NO_DATA_MARK):].strip())
    reason = (f'<div style="font-size:11px;color:#7a5600;margin-top:4px">'
              f'{_html.escape(why)}</div>') if why else ""
    return (f'<div style="font-size:12px;color:#9a6b00;background:#fff4d6;'
            f'border:1px solid #f0d271;border-radius:4px;padding:8px 10px;'
            f'margin:4px 0 10px">— {what} {PENDING_MARK} '
            f'(re-run after fixing the source) —{reason}</div>')


def _no_data(what: str, detail: str = "") -> str:
    """The source ran fine and had nothing to report — a real zero.

    Grey like _not_available and, like it, WITHOUT PENDING_MARK: a captain
    whose ICDs simply did not knock on a Sunday must not have his report held
    back by run.py's send guard, and Eve must not be sent hunting for a broken
    source that isn't broken. The detail (e.g. "no knocks recorded yesterday")
    still says WHICH zero it is, so an office that goes quiet for a week is
    still visible rather than silently blank — the standing rule."""
    tail = f' — {_html.escape(detail)}' if detail else ""
    return (f'<div style="font-size:12px;color:#555;background:#f4f4f4;'
            f'border:1px solid #ddd;border-radius:4px;padding:8px 10px;'
            f'margin:4px 0 10px">{what}: no data available{tail}.</div>')


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
    elif kind in ("knock_dispo", "daily_knocks"):
        # Per-owner knock boards — ONE branch for both the weekly boards
        # (knock_dispo, Raf's Loom 2026-08-23, Sun/Mon only) and the daily
        # boards (daily_knocks, Raf's Slack 2026-08-23 evening, every day):
        # identical [(title, png|None), …] bundle contract, identical
        # per-owner isolation. A small owner sub-heading, then that owner's
        # board; a single owner's failed pull renders as a pending note under
        # THEIR name — the other owners' boards still show. An empty list
        # means the roster/session itself failed, so the section carries ONE
        # note with that reason instead.
        what = ("Weekly Knock Dispositions" if kind == "knock_dispo"
                else "Daily Knocks")
        items = bundle.get(kind) or []
        if not items:
            body += _pending(f"{what} boards", err.get(kind, ""))
        for i, (owner, path) in enumerate(items):
            body += (f'<div style="font-size:14px;font-weight:bold;'
                     f'margin:14px 0 4px">{_html.escape(owner)}</div>')
            body += (imgs.img(path, slot=f"{kind.replace('_', '-')}-{i}")
                     if path
                     else _pending(f"{_html.escape(owner)}'s {what} board",
                                   err.get(f"{kind}:{owner}", "")))
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


def _attach(msg: EmailMessage, pdf_path, filename: str) -> None:
    msg.add_attachment(Path(pdf_path).read_bytes(), maintype="application",
                       subtype="pdf", filename=filename)


def attach_within_limit(msg: EmailMessage, bundle: dict) -> List[str]:
    """Attach the PDFs in the order Rafael reads the report — last week, then
    the captainship's day, then each owner's own page (Eve 2026-09-01) — and
    return the names of any that did not fit.

    The first two are never dropped: between them they cover everybody. The
    per-owner copies are added while the ASSEMBLED message stays under
    MAX_MESSAGE_BYTES, measured after each one rather than estimated, because
    the inline boards in the body weigh as much as the attachments do and a
    fixed attachment budget cannot see them.

    Dropping is the last resort and should stay unreached — say so in the body
    when it happens (build does), since an attachment that vanishes silently is
    worse than one that is missing loudly."""
    weekly = bundle.get("weekly_pdf")
    dailies = list(bundle.get("daily_pdfs") or [])
    for item in ([weekly] if weekly else []) + dailies[:1]:
        _attach(msg, *item)
    dropped: List[str] = []
    for pdf_path, filename in dailies[1:]:
        _attach(msg, pdf_path, filename)
        if len(bytes(msg)) > MAX_MESSAGE_BYTES:
            # Undo: the parts list is the only place it landed.
            msg.get_payload().pop()
            dropped.append(filename)
    return dropped


def _note_dropped(msg: EmailMessage, dropped: List[str]) -> None:
    """Append the 'these did not fit' line to the message's HTML body."""
    from automations.captainship_drafts.daily_pdf import owner_of
    who = ", ".join(owner_of(n) for n in dropped)
    note = ('<div style="font-size:12px;color:#666;margin-top:10px">'
            f'{len(dropped)} per-owner Daily Knock Dispositions PDF(s) were '
            'left off to keep this email under the mail size limit: '
            f'{_html.escape(who)}.</div>')
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            body = part.get_content()
            part.set_content(body.replace("<br>Kind regards,",
                                          note + "<br>Kind regards,", 1),
                             subtype="html")
            return


def build(captain: Captain, bundle: dict, today: dt.date) -> EmailMessage:
    """Build the draft message for `captain` from its image `bundle`.

    bundle keys: product_summary(Path), units([(cap,Path)]),
    fiber_activation(Path), cancel_tableau(Path), teamstats_tableau(Path),
    churn_ni([(cap,Path)]), churn_wireless([(cap,Path)]),
    boxes({slot: Path}), knock_dispo([(owner, Path|None)]),
    daily_knocks([(owner, Path|None)]),
    errors({bundle key: reason}).  Missing keys render as a per-section
    'pending' note, carrying that key's reason when there is one.

    Sections come from captain.body_sections_on(today) — a day-gated section
    is simply not in the body OR the intro on its off days, even if its bundle
    key is populated, and an attachment-only kind (knock_dispo since
    2026-09-01) is never in the body at all: it rides as the weekly PDF."""
    msg = EmailMessage()
    msg["Subject"] = subject_for(captain, today)
    msg["From"] = FROM_ADDR
    msg["To"] = ""   # blank on purpose — reviewer fills before sending

    msg.set_content(
        "This Captainship Report is best viewed in an HTML email client.\n\n"
        "Kind regards,\n\n" + _SIGNATURE_TEXT_BODY)

    imgs = _Images()
    sections_html = "".join(
        _section_html(captain, heading, kind, n, bundle, imgs)
        for n, (heading, kind) in enumerate(
            captain.body_sections_on(today), 1))

    # Same short/semantic scheme as the section images (see _Images) — the
    # signature photo is just the last part in the same related bundle.
    cid_photo = f"<{len(imgs.pairs) + 1:02d}-signature@{_Images._DOMAIN}>"
    html = (
        f'<div style="font-family:{_FONT_STACK};color:#000">'
        f'{_notice_html()}'
        f'{_intro_html(captain, today)}'
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
        # NOT read_bytes(): a board wider than any client can show is
        # pre-shrunk with one clean Lanczos pass + a mild unsharp, so the mail
        # client is left a gentle final shrink instead of a 3x one it does with
        # cheap sampling. Same helper the Org Sales Board email uses — that
        # blur was Raf's 2026-08-23 report and this email never got the fix
        # (Megan 2026-08-30: everything we hand anyone should be as
        # fit-to-screen as possible WITHOUT losing sharpness). A board already
        # inside the cap is passed through byte-for-byte.
        html_part.add_related(_beh.inline_image_bytes(path, _INLINE_PX),
                              maintype="image", subtype="png", cid=cid)
    html_part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                          maintype="image", subtype="png", cid=cid_photo)

    # Last week's Knock Dispositions boards as a real attachment (Rafael
    # 2026-08-27) — see weekly_pdf. This is add_attachment on the TOP-LEVEL
    # message, which is the distinction the comment above is about: it wraps
    # the whole thing in a multipart/mixed and leaves the inline images inside
    # their own multipart/related, untouched. What broke in 2026-07-27 was
    # NAMING a part inside that related container, which turned an inline
    # image into an attachment; a genuine attachment alongside the container
    # is the shape every mail client expects. It also no longer passes through
    # a Gmail draft rewrite at all — the send is SMTP with this exact MIME.
    dropped = attach_within_limit(msg, bundle)
    if dropped:
        # Said in the body, not just in a log nobody reads: the captain has to
        # know an office's page is missing rather than assume it never existed.
        _note_dropped(msg, dropped)
    return msg
