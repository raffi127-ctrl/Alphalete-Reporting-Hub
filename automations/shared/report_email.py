"""ONE way to email a set of report boards to people who aren't in Slack.

WHY THIS EXISTS. Every daily feed we run — office metrics, the Tableau trackers —
delivers by posting images into a Slack thread. Joseph Logan (Logan Legacy Group)
asked for the daily metrics and has no Slack account at all (Megan 2026-09-13), so
"his channel" is an inbox. Rather than teach each metric module a second delivery
channel, the boards it already renders are collected and mailed as ONE message.

ONE EMAIL PER FEED PER DAY, not one per board. A Slack thread is a container —
eleven replies under one header still read as one thing. An inbox has no
container, so eleven mails is eleven interruptions. The thread's header becomes
the mail's subject + intro, and its replies become the rows of one message.

LAYOUT IS NOT REINVENTED HERE. shared.board_email_html is the single-column
presentation table every board email we send already uses — bare <img> tags flow
side-by-side in Gmail, and the on-disk preview does NOT reproduce it. Images go
through inline_image_bytes so an oversized render is downsampled once, cleanly,
instead of being mangled by the client's cheap scaler.

FROM alphaletereporting@gmail.com over Gmail SMTP (SSL 465) with the app password
from ~/.config/recruiting-report/gmail-app-password — the same sender and the same
credential as every other automated email this repo sends. Nothing new to install.

    from automations.shared import report_email
    report_email.send_boards(
        subject="Daily Metrics — September 13",
        to=["joseph@loganlegacygroup.com"],
        title="DAILY METRICS — LOGAN LEGACY GROUP",
        blocks=[("Total Knocks", Path("...png")), ...],
        dry_run=True)          # writes the preview, sends nothing
"""
from __future__ import annotations

import datetime as dt
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Sequence, Tuple

from automations.shared import board_email_html as _beh
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password,
    PHOTO_EMBED_PX, PHOTO_IMG, _signature_html, _circular_photo_png,
    _SIGNATURE_TEXT,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# What one message may weigh ON THE WIRE. Gmail refuses at 25 MB and base64
# inflates bytes by ~37%, so the budget is set in encoded terms and kept well
# under the cliff: a tracker board grows when a campaign adds rows, and the day
# it crosses 25 MB the send fails — silently, to an inbox, which is the one
# failure mode this whole path has to avoid.
MAX_WIRE_BYTES = 20 * 1024 * 1024
# Where Gmail actually refuses. The budget above sits under it on purpose; this
# is only the backstop that turns a refusal into a sentence someone can act on.
GMAIL_HARD_LIMIT = 24 * 1024 * 1024
_B64_OVERHEAD = 1.37

# Widths the ladder tries, biggest first, when a set is over budget. 2400 is the
# inline cap (what a mail client can actually paint); below that a dense board
# starts losing gridlines, so the ladder stops rather than shrinking forever.
_ATTACH_LADDER = (3000, 2400, 1800)


def _wire_size(parts: "Sequence[bytes]") -> int:
    return int(sum(len(b) for b in parts) * _B64_OVERHEAD)


def _fit_attachments(items: "List[Tuple[str, Path]]") -> Tuple[list, list]:
    """([(filename, bytes)], [names that had to be reduced]).

    FULL RESOLUTION IS THE POINT of attaching these — the boards are 3400px wide
    and the whole reason they are attachments rather than inline images is that a
    mail column crushes them. So the original bytes go out untouched whenever the
    set fits, and only an over-budget set is stepped down, biggest boards first,
    until it does. Reducing something is reported, never silent: a board that
    quietly lost half its pixels reads as a rendering bug to whoever opens it.
    """
    out = [(n, Path(p).read_bytes()) for n, p in items]
    if _wire_size([b for _n, b in out]) <= MAX_WIRE_BYTES:
        return out, []
    reduced: List[str] = []
    for cap in _ATTACH_LADDER:
        # Step the heaviest boards down first — that is where the bytes are, and
        # it leaves the small ones (which are already legible) alone.
        order = sorted(range(len(out)), key=lambda i: len(out[i][1]), reverse=True)
        for i in order:
            if _wire_size([b for _n, b in out]) <= MAX_WIRE_BYTES:
                break
            name, _ = out[i]
            src = Path(items[i][1])
            try:
                small = _beh.inline_image_bytes(src, max_px=cap)
            except Exception:                        # noqa: BLE001
                continue
            if len(small) < len(out[i][1]):
                out[i] = (name, small)
                if name not in reduced:
                    reduced.append(name)
        if _wire_size([b for _n, b in out]) <= MAX_WIRE_BYTES:
            break
    return out, reduced


def _attachment_name(label: str, path: Path) -> str:
    """A filename someone can find again in their downloads folder — the board's
    own name, not `att_country.png`. Only the characters a filesystem or a mail
    client would choke on are replaced."""
    clean = "".join("-" if c in '/\\:*?"<>|' or ord(c) < 32 else c
                    for c in str(label)).strip()
    return (clean or path.stem) + (path.suffix or ".png")

# A block whose image is missing/empty. It still gets a LINE, because a board
# that was promised and did not arrive has to be visible as absent — an email
# that silently drops it reads as a complete day [[feedback_fill_but_flag]].
_MISSING = ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;'
            'color:#8a0000;padding:6px 0">⚠️ {label} — not available today.</div>')


_ATTACHED = ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;'
             'padding:6px 0">📎 {label} — attached to this email.</div>')


def _readable_image(path) -> bool:
    """Can this file actually be decoded as an image?

    A capture directory does not only hold PNGs. The Order Log posts a
    SPREADSHEET, and for an email-only office that .xlsx is copied in beside the
    boards. Embedding it raised UnidentifiedImageError out of
    inline_image_bytes and took the whole send down with it: on 2026-09-14
    Joseph's five rendered boards reached nobody because the sixth was an .xlsx.

    Non-images are now classified at capture time and attached instead, so this
    is the BACKSTOP rather than the mechanism — whatever ends up in a blocks
    list, a file we cannot draw is one block we cannot draw, never a reason to
    mail nobody anything [[feedback_fill_but_flag]].
    """
    try:
        from PIL import Image
        with Image.open(path):
            return True
    except Exception:                                # noqa: BLE001
        return False


def kind_of(block: Sequence) -> str:
    """A block's 4th element: "" = a board image, "note" = a section that ran and
    had nothing to show, "missing" = a board that was owed and did not arrive,
    "attached" = it came as a file on this email rather than a picture in it.

    THE DISTINCTION MATTERS. "Order Log — no new orders today" and "Order Log —
    didn't render" look identical if both are drawn as a bare line, and they are
    opposite facts: one is a clean day, the other is a hole in the report. Only
    the second gets the warning [[feedback_fill_but_flag]].
    """
    return str(block[3]) if len(block) > 3 and block[3] else ""


def _rows_for(blocks: Sequence, *, title: str, intro_html: str) -> Tuple[list, list]:
    """(html rows, [(cid, image path)]) for the boards, in the order given.

    A block is (label, path[, sheet_px[, kind]]). A block with no usable image is
    a note or a miss depending on `kind` — see kind_of — so the mail can never
    quietly be short a board, and never cry wolf over a quiet one.
    """
    have = [b for b in blocks
            if b[1] and Path(b[1]).exists() and _readable_image(b[1])]
    widest = _beh.scale_of(have)
    rows: List[str] = [_beh.banner_row(title)]
    if intro_html:
        rows.append(_beh.text_row(intro_html))
    cids: List[Tuple[str, Path]] = []
    for b in blocks:
        label, path = b[0], b[1]
        if not path or not Path(path).exists() or not _readable_image(path):
            kind = kind_of(b)
            if kind == "note":
                rows.append(_beh.text_row(
                    f'<div style="padding:6px 0">{label}</div>'))
            elif kind == "attached":
                rows.append(_beh.text_row(_ATTACHED.format(label=label)))
            else:
                rows.append(_beh.text_row(_MISSING.format(label=label)))
            continue
        # Each board keeps its own caption: in a thread the reply text says what
        # the image is, and dropping it in the mail would leave a wall of tables.
        rows.append(_beh.text_row(
            f'<div style="font-weight:bold;padding:4px 0 6px">{label}</div>'))
        cid = make_msgid()[1:-1]
        cids.append((cid, Path(path)))
        rows.append(_beh.image_row(cid, alt=str(label),
                                   width_px=_beh.sheet_px(b), widest_px=widest))
    return rows, cids


def _attach_rows(blocks: Sequence, *, title: str, intro_html: str,
                 reduced: Sequence[str]) -> list:
    """The body for an ATTACHMENT email: what arrived, by name, in order.

    No inline copies. A board that is attached BECAUSE the mail column crushes it
    gains nothing from also being painted in that column — it just doubles the
    message and puts a wall of unreadable thumbnails between the reader and the
    files. So the body is the index: every board listed in posting order, notes
    and misses in their place, and the attachments carry the pixels.
    """
    rows: List[str] = [_beh.banner_row(title)]
    if intro_html:
        rows.append(_beh.text_row(intro_html))
    # The numbered list is THE ATTACHMENTS and nothing else — a board that isn't
    # a file in this email must not be numbered among the files, or the count
    # under the list disagrees with the list itself.
    attached, other = [], []
    for b in blocks:
        label, path = b[0], b[1]
        if path and Path(path).exists():
            attached.append(f"<li>{label}</li>")
        elif kind_of(b) == "note":
            other.append(f'<div style="color:#555;padding:2px 0">{label}</div>')
        else:
            other.append(f'<div style="color:#8a0000;padding:2px 0">⚠️ {label} '
                         "— not available today.</div>")
    body = ""
    if attached:
        body += ('<div style="padding:0 0 8px">Attached to this email, one file '
                 'each:</div>'
                 f'<ol style="margin:0 0 12px 20px;padding:0">{"".join(attached)}</ol>'
                 '<div style="padding:0 0 8px;color:#555">Open any one to see it '
                 'full-size — they are too wide to read inside an email.</div>')
    if other:
        body += ('<div style="padding:12px 0 4px;font-weight:bold">Also today:'
                 '</div>' + "".join(other))
    rows.append(_beh.text_row(body))
    if reduced:
        # Said out loud, because the reader's expectation for an attachment is
        # "the original", and a board that silently lost pixels reads as a bug.
        rows.append(_beh.text_row(
            '<div style="color:#8a0000">Today\'s set was too large to send at '
            'full size, so these were reduced: ' + ", ".join(reduced) + ".</div>"))
    return rows


def _file_attachment(label: str, path: Path) -> Tuple[str, bytes, str, str]:
    """(filename, bytes, maintype, subtype) for a non-image board.

    The type is guessed from the suffix and falls back to
    application/octet-stream, which every client will still save — better a
    generic attachment than no Order Log.
    """
    import mimetypes
    ctype, _enc = mimetypes.guess_type(path.name)
    maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
    # _attachment_name already does the "name it for the board, not the working
    # file" job for image attachments — the owner should see "Order Log.xlsx",
    # not the capture directory's "08---Order-Log---Sep-14.xlsx".
    return (_attachment_name(label, path), path.read_bytes(),
            maintype, (subtype or "octet-stream"))


def build_message(*, subject: str, to: Sequence[str], title: str,
                  blocks: Sequence, intro_html: str = "",
                  reply_to: str = "", attach: bool = False,
                  files: Sequence = ()) -> EmailMessage:
    """The email, images inline, Evelyn's signature at the bottom (the same block
    every automated mail from this account carries, built from ONE definition in
    scheduled_6_days_out so her title/photo change in one place)."""
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to

    attachments: List[Tuple[str, bytes]] = []
    if attach:
        have = [(b[0], Path(b[1])) for b in blocks
                if b[1] and Path(b[1]).exists()]
        named = [(_attachment_name(lbl, pth), pth) for lbl, pth in have]
        attachments, reduced = _fit_attachments(named)
        rows, cids = _attach_rows(blocks, title=title, intro_html=intro_html,
                                  reduced=reduced), []
    else:
        rows, cids = _rows_for(blocks, title=title, intro_html=intro_html)
    cid_photo = make_msgid()[1:-1]
    rows.append(_beh.text_row("Best,<br><br>" + _signature_html(f"<{cid_photo}>")))
    html = _beh.document(rows)

    plain = "\n".join([title, "",
                       *[f"- {b[0]}" for b in blocks],
                       "", "See the HTML version for the boards.", "",
                       _SIGNATURE_TEXT])
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    part = msg.get_payload()[-1]
    for cid, path in cids:
        part.add_related(_beh.inline_image_bytes(path), "image", "png",
                         cid=f"<{cid}>")
    part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                     maintype="image", subtype="png", cid=f"<{cid_photo}>")
    # Attachments hang off the MESSAGE, not the html part — a file added to the
    # related part becomes an inline resource of the body instead of something
    # the reader can save, which is the whole point here.
    for fname, data in attachments:
        msg.add_attachment(data, maintype="image", subtype="png",
                           filename=fname)
    # Non-image boards (the Order Log's .xlsx). Best-effort per file: one
    # unreadable spreadsheet must not cost the owner the boards that DID render
    # — the exact failure this path was built after.
    for label, path in (files or ()):
        try:
            fname, data, maintype, subtype = _file_attachment(label, Path(path))
            msg.add_attachment(data, maintype=maintype, subtype=subtype,
                               filename=fname)
        except Exception:                            # noqa: BLE001
            continue
    return msg


def send_message(msg: EmailMessage) -> None:
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(FROM_ADDR, app_password())
        s.send_message(msg)


def send_boards(*, subject: str, to: Sequence[str], title: str,
                blocks: Sequence, intro_html: str = "", reply_to: str = "",
                attach: bool = False, files: Sequence = (),
                dry_run: bool = False,
                preview_dir: "Path | None" = None, logfn=print) -> dict:
    """Build + send (or, with dry_run, build + write the preview and send NOTHING).

    Returns a dict either way, so a caller can log what went where without
    branching on the mode. `preview_dir` defaults to output/report_email/<date>.
    """
    to = [a.strip() for a in to if (a or "").strip()]
    if not to:
        return {"ok": False, "skipped": True, "reason": "no recipients"}
    msg = build_message(subject=subject, to=to, title=title, blocks=blocks,
                        intro_html=intro_html, reply_to=reply_to, attach=attach,
                        files=files)
    # HARD BACKSTOP. The ladder in _fit_attachments stops at the legibility floor
    # rather than shrinking a dense board into mush, so a genuinely enormous day
    # can still come out over Gmail's limit. Catch it HERE with a sentence that
    # names the size, instead of letting SMTP reject the message with an opaque
    # error after the whole morning's work — and instead of the boards going
    # quietly nowhere, which is this path's worst failure mode.
    _wire = len(bytes(msg))
    if _wire > GMAIL_HARD_LIMIT:
        return {"ok": False, "to": to, "subject": subject,
                "reason": (f"message is {_wire/1024/1024:.1f} MB — over Gmail's "
                           f"{GMAIL_HARD_LIMIT/1024/1024:.0f} MB limit even after "
                           f"reducing the largest boards. Split the day's boards "
                           f"across two sends, or drop one from this office's set.")}
    n_img = sum(1 for b in blocks if b[1] and Path(b[1]).exists())
    # A note is not a miss — counting it as one turns every quiet day into an
    # alarm in the run log.
    n_missing = sum(1 for b in blocks
                    if not (b[1] and Path(b[1]).exists())
                    and kind_of(b) != "note")

    out = preview_dir or (REPO_ROOT / "output" / "report_email"
                          / dt.date.today().isoformat())
    out.mkdir(parents=True, exist_ok=True)
    stem = "".join(c if c.isalnum() else "-" for c in subject)[:60].strip("-")
    (out / f"{stem}.eml").write_bytes(bytes(msg))

    _how = "attached" if attach else "inline"
    if dry_run:
        logfn(f"[report_email] DRY RUN — nothing sent.\n"
              f"  to: {', '.join(to)}\n  subject: {subject}\n"
              f"  {n_img} board(s) {_how}"
              + (f", {n_missing} MISSING" if n_missing else "") +
              f"\n  preview: {out / (stem + '.eml')}")
        return {"ok": True, "dry_run": True, "to": to, "subject": subject,
                "boards": n_img, "missing": n_missing}

    send_message(msg)
    _mb = len(bytes(msg)) / 1024 / 1024
    logfn(f"[report_email] sent to {', '.join(to)} — {n_img} board(s) {_how}"
          + (f", {n_missing} MISSING" if n_missing else "")
          + f" ({_mb:.1f} MB)")
    return {"ok": True, "to": to, "subject": subject, "attached": attach,
            "boards": n_img, "missing": n_missing, "size_mb": round(_mb, 1)}
