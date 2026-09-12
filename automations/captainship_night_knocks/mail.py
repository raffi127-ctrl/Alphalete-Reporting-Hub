"""The night-knocks email: one thread per captain, one message per wave.

WHAT MAKES THIS DIFFERENT FROM EVERY OTHER MAIL IN THE REPO is that a night is
not one message. Raf's ask (2026-09-07): the Florida offices land at 8 PM
Central, Texas REPLIES into that same thread at 9, California at 11. So the
first wave of a night opens a thread and every later wave answers it — which is
only possible if we keep the first message's Message-ID. `Thread` below is that
memory, and `state.py` is where it survives between the 5-minute ticks that
actually do the sending.

THREADING IS THREE HEADERS AND ONE SUBJECT RULE. In-Reply-To and References
both carry the parent's Message-ID (clients disagree about which they honour —
the same belt-and-braces as captainship_drafts.reply_attachment), and the
subject must stay the SAME string with "Re: " in front. Gmail collapses on the
subject as much as on the headers: change one word between waves and the
captain gets two conversations, which is the exact thing this design exists to
avoid.

SAMPLE MODE IS A RECIPIENT ALLOWLIST, NOT A FLAG THAT DECORATES THE SUBJECT.
The first weekend this runs, it runs unattended off zones a scraper harvested
(zones.enable_harvested) and nobody is watching. `assert_allowed()` is what
makes that safe: in sample mode the message physically cannot go to anyone but
Raf and Eve, and it raises rather than dropping a recipient quietly. A wrong
zone then costs those two an email at an odd hour, and costs an ICD nothing.
"""
from __future__ import annotations

import datetime as dt
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from automations.captainship_drafts.email_build import _Images, _INLINE_PX
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password,
)
from automations.shared import board_email_html as _beh

# WHO THE SAMPLE GOES TO. Eve, 2026-09-11: "enviarlo solo a Rafael Hidalgo
# <raffi127@gmail.com> y eve@alphaletemarketing.com". Nobody else, and no
# fallback — an address that is not on this list is a bug in the caller, not a
# recipient to drop silently.
SAMPLE_RECIPIENTS: Tuple[str, ...] = ("raffi127@gmail.com",
                                      "eve@alphaletemarketing.com")

SUBJECT_TAG = "[SAMPLE] "


class RecipientError(RuntimeError):
    """Raised when a send would reach somebody sample mode does not allow."""


def assert_allowed(to_addrs: Sequence[str], *, sample: bool) -> List[str]:
    """The recipients to use, or raise. In sample mode the list is pinned."""
    if not sample:
        out = [a.strip() for a in to_addrs if a and a.strip()]
        if not out:
            raise RecipientError("live send with no recipients")
        return out
    allowed = {a.lower() for a in SAMPLE_RECIPIENTS}
    bad = [a for a in to_addrs if a.strip().lower() not in allowed]
    if bad:
        raise RecipientError(
            "sample mode may only mail %s — refused: %s"
            % (", ".join(SAMPLE_RECIPIENTS), ", ".join(bad)))
    return list(SAMPLE_RECIPIENTS)


@dataclass
class Thread:
    """One captain's conversation for one night.

    `message_id` is the FIRST wave's id: every later wave replies to that one
    rather than to the previous reply, so the thread stays flat and a wave that
    failed cannot orphan the ones after it.
    """
    subject: str
    message_id: Optional[str] = None
    references: List[str] = field(default_factory=list)

    def headers_for_next(self) -> Dict[str, str]:
        if not self.message_id:
            return {}
        refs = " ".join(self.references or [self.message_id])
        return {"In-Reply-To": self.message_id, "References": refs}

    def subject_for_next(self) -> str:
        return self.subject if not self.message_id else "Re: " + self.subject

    def remember(self, message_id: str) -> None:
        if not self.message_id:
            self.message_id = message_id
        if message_id not in self.references:
            self.references.append(message_id)

    def to_json(self) -> dict:
        return {"subject": self.subject, "message_id": self.message_id,
                "references": list(self.references)}

    @classmethod
    def from_json(cls, raw: Optional[dict], subject: str) -> "Thread":
        raw = raw or {}
        return cls(subject=raw.get("subject") or subject,
                   message_id=raw.get("message_id"),
                   references=list(raw.get("references") or []))


def subject_for(captain_display: str, local_date: dt.date, *,
                sample: bool) -> str:
    """'Daily Knocks - Raf's Captainship - Sat 9/12'. The DATE IS THE ICDs'
    OWN and it never changes between waves: all three messages in a thread
    close the same knocking day, even though the 11 PM one is sent after
    midnight Central."""
    day = "%s %d/%d" % (local_date.strftime("%a"), local_date.month,
                        local_date.day)
    base = "Daily Knocks — %s — %s" % (captain_display, day)
    return (SUBJECT_TAG + base) if sample else base


def _clock(when: dt.datetime) -> str:
    """'9:00 PM' — built by hand, never %-I (glibc only, throws on Windows)."""
    return "%d:%02d %s" % (when.hour % 12 or 12, when.minute,
                           "AM" if when.hour < 12 else "PM")


def _wave_intro(label: str, icds: Sequence[str], fire_local: dt.datetime,
                first: bool) -> str:
    who = ", ".join(icds)
    lead = ("Tonight's knocking, as each office finishes its day."
            if first else "Next wave — these offices have now finished.")
    return ('<p style="margin:0 0 10px">%s</p>'
            '<p style="margin:0 0 16px;color:#555">'
            '<b>%s</b> · %s local · %s</p>'
            % (lead, label, _clock(fire_local), who))


def build(*, subject: str, label: str, icds: Sequence[str],
          fire_local: dt.datetime, boards: Sequence[Tuple[str, Optional[Path]]],
          notes: Sequence[str] = (), footer: Sequence[str] = (),
          first: bool, to_addrs: Sequence[str],
          extra_headers: Optional[Dict[str, str]] = None) -> EmailMessage:
    """The wave's message. `boards` is [(title, png or None), …] — a None path
    is printed as a visible absence, never as a blank board (standing rule)."""
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    for k, v in (extra_headers or {}).items():
        msg[k] = v

    imgs = _Images()
    blocks: List[str] = []
    for title, png in boards:
        ok = False
        try:
            ok = bool(png) and Path(png).exists() and Path(png).stat().st_size > 0
        except OSError:
            ok = False
        if ok:
            blocks.append(imgs.img(png, slot=title, caption=title))
        else:
            blocks.append(
                '<div style="font-size:13px;font-weight:bold;margin:12px 0 4px">'
                '%s</div><div style="font-size:13px;color:#777;padding:8px 10px;'
                'background:#f4f4f4;border:1px solid #ddd">no knocks recorded'
                '</div>' % title)

    note_html = ""
    if notes:
        note_html = ('<ul style="font-size:13px;color:#777;margin:14px 0 0">'
                     + "".join("<li>%s</li>" % n for n in notes) + "</ul>")
    foot_html = ""
    if footer:
        foot_html = ('<div style="font-size:12px;color:#999;margin-top:18px;'
                     'border-top:1px solid #eee;padding-top:10px">'
                     + "<br>".join(footer) + "</div>")

    msg.set_content("\n".join([subject, ""] + [t for t, _ in boards]))
    msg.add_alternative(
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px">'
        + _wave_intro(label, icds, fire_local, first)
        + "".join(blocks) + note_html + foot_html + "</div>",
        subtype="html")

    html_part = msg.get_payload()[1]
    # Bare add_related (inline, unnamed) — never filename=. See the warning in
    # captainship_drafts.email_build.build: a named part reads to Gmail as a
    # real attachment and the inline cid refs break.
    for cid, path, _fn in imgs.pairs:
        html_part.add_related(_beh.inline_image_bytes(path, _INLINE_PX),
                              maintype="image", subtype="png", cid=cid)
    return msg


def _ssl_context():
    # certifi's bundle — the python.org macOS build ships without system CAs,
    # so a default context fails verification on the minis.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def send(msg: EmailMessage, to_addrs: Sequence[str], *, logfn=print) -> str:
    """Send over SMTP and return the Message-ID the thread must remember.

    The id is stamped HERE rather than left to the server: a reply needs the
    parent's id and we cannot read it back out of a message already sent.
    """
    if not msg["Message-ID"]:
        from email.utils import make_msgid
        msg["Message-ID"] = make_msgid(domain="alphalete.report")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=_ssl_context()) as conn:
        conn.login(FROM_ADDR, app_password())
        conn.send_message(msg, from_addr=FROM_ADDR, to_addrs=list(to_addrs))
    logfn("[night-knocks] sent %r to %s" % (msg["Subject"], ", ".join(to_addrs)))
    return msg["Message-ID"]


def send_plain(subject: str, body_html: str, to_addrs: Sequence[str], *,
               extra_headers: Optional[Dict[str, str]] = None,
               logfn=print) -> str:
    """A text/HTML-only message — what the failure notice uses.

    Deliberately shares nothing with `build()` beyond SMTP: the whole point of
    the failure notice is that it still goes out on a night when board building
    is what broke.
    """
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    for k, v in (extra_headers or {}).items():
        msg[k] = v
    msg.set_content("This message is HTML. " + subject)
    msg.add_alternative(
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px">'
        + body_html + "</div>", subtype="html")
    return send(msg, to_addrs, logfn=logfn)
