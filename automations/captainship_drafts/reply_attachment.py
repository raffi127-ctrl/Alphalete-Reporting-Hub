"""Reply to a Captainship Report that ALREADY WENT OUT, attaching last week's
Knock Dispositions PDF.

Rafael's ask (Slack, 2026-08-30, via Megan): "can we resend the peoples
captainship emails. just the attachment?" — then, when told a rebuild-and-resend
was a two-hour job: "yeah let it build and resend", and Megan settled the shape:
*"no, just respond to the emails already sent today with their attachments"*.

So this does NOT rebuild or re-send a report. It finds the message that was
already delivered, and answers it in its own thread with one PDF attached. The
captain sees a reply under the report he already has, not a second copy of it.

WHY A REPLY AND NOT A FRESH MAIL. The reports carry ~20 inline board images and
run 8-15MB; sending another is expensive, and a second copy of a report someone
already read is how a reader stops trusting which one is current. A reply is a
few hundred KB, threads under the original in every client, and is unambiguous
about what changed.

WHAT IT NEEDS, and why each part exists:

  * the ORIGINAL message. Found over IMAP in the sending account's Sent folder
    by its exact Subject (config.subject_for), so the reply can carry
    In-Reply-To / References and thread properly. No Message-ID = no reply: we
    do not fall back to a fresh mail, because an untethered copy is precisely
    what Megan ruled out.
  * the RECIPIENTS. Taken from the original's To/Cc, never from config — the
    people who got the report are the people who get the answer to it, even if
    a roster has changed since. (A captain removed from config this morning
    would otherwise be silently dropped from a reply to mail he received.)
  * the PDF, RE-PRINTED here from the boards on disk, never read from an
    older file. Rafael's PDF on the mini was printed at 12:55 today, before the
    columns he asked for existed; attaching that would have answered his
    request with the layout he asked us to change. No boards = that captain is
    SKIPPED and said so; never a reply promising an attachment it lacks.

SAFETY. --dry-run is the default and prints exactly what would go where.
Sending needs --send, and every send is logged with the recipient list. Only
the six FIBER captainships can be targeted at all: b2b/nds reports have no
knock_dispo section, so there is no weekly PDF for them and asking for one is
an error rather than an empty mail.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import imaplib
import sys
from email.message import EmailMessage
from email.utils import getaddresses, formataddr
from pathlib import Path
from typing import List, Optional, Tuple

from automations.captainship_drafts import config

IMAP_HOST = "imap.gmail.com"
# Gmail exposes Sent under this name via IMAP regardless of the UI language.
SENT_MAILBOX = '"[Gmail]/Sent Mail"'

BODY = (
    "Hi team,\n\n"
    "Attached is the Weekly Knock Dispositions report for {span}, updated with "
    "the columns Rafael asked for.\n"
    "{missing}"
    "\nNothing else in the report below has changed.\n\n"
    "— Alphalete Reporting\n"
)

# The line naming offices the PDF does NOT cover (Megan 2026-08-30, choosing
# this over sending only the complete ones or sending the gaps unexplained).
#
# WHY IT HAS TO BE SAID, AND WHY IT NAMES RAFAEL. A captain who has nine
# offices and opens a PDF with three reads the REPORT as broken. It isn't: the
# whole report runs on Rafael's OwnerVille login, and an office that is not in
# HIS Office Access cannot be pulled for anyone. Saying "the reporting account"
# left readers guessing whose account and what to do about it (Megan
# 2026-08-30) — naming Rafael's makes the fix obvious and puts it with the
# person who can grant it. Wayne is the sharp end: 6 of his 6 ICDs were
# unreachable on the 2026-08-30 pull.
MISSING_LINE = (
    "\nNot included: {names}. Rafael's OwnerVille login doesn't have Office "
    "Access to those offices, so the report can't pull them and they have no "
    "page in this PDF. Once they're added to his access they'll appear "
    "automatically.\n")


def missing_offices(render_dir, captain_key: str, saturday) -> List[str]:
    """The owners this captain's capture could NOT produce a board for, newest
    manifest wins. Read from the manifest rather than diffed against a roster:
    the manifest is what the capture actually saw, so an office added or
    renamed this morning can't turn into a phantom "missing" line."""
    import json
    newest = None
    pat = f"knocks_manifest_{captain_key}_*_{saturday.isoformat()}.json"
    for man in sorted(Path(render_dir).glob(pat), reverse=True):
        try:
            data = json.loads(man.read_text(encoding="utf-8"))
        except Exception:      # noqa: BLE001 — an unreadable one is not fatal
            continue
        pairs = (data.get("items") or {}).get("knock_dispo")
        if pairs:
            newest = pairs
            break
    if not newest:
        return []
    return [lab.split(" — ")[0].strip() for lab, path in newest if not path]


def _addrs(msg, header: str) -> List[str]:
    """Every address on one header of the original, de-duplicated in order."""
    out, seen = [], set()
    for name, addr in getaddresses(msg.get_all(header, []) or []):
        a = (addr or "").strip()
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(formataddr((name, a)) if name else a)
    return out


def find_sent(subject: str, account: str, password: str,
              *, logfn=print) -> Optional[dict]:
    """The already-sent message with this exact Subject, as
    {message_id, to, cc, subject, date}. None when it isn't there — which is
    the honest answer for a report that never went out."""
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(account, password)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ✗ IMAP login failed: {type(e).__name__}: {str(e)[:160]}")
        return None
    try:
        M.select(SENT_MAILBOX, readonly=True)
        # HEADER SUBJECT does a substring match; the exact string is compared
        # again below, so a near-miss subject can never be answered by mistake.
        typ, data = M.search(None, 'HEADER', 'SUBJECT', f'"{subject}"')
        if typ != "OK" or not data or not data[0]:
            return None
        best = None
        for num in data[0].split():
            typ, raw = M.fetch(num, "(BODY.PEEK[HEADER])")
            if typ != "OK" or not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            if (msg.get("Subject") or "").strip() != subject.strip():
                continue
            mid = (msg.get("Message-ID") or "").strip()
            if not mid:
                continue
            best = {"message_id": mid, "to": _addrs(msg, "To"),
                    "cc": _addrs(msg, "Cc"),
                    "subject": (msg.get("Subject") or "").strip(),
                    "date": (msg.get("Date") or "").strip(),
                    "references": (msg.get("References") or "").strip()}
        return best
    except Exception as e:  # noqa: BLE001
        logfn(f"  ✗ IMAP search failed: {type(e).__name__}: {str(e)[:160]}")
        return None
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def build_reply(original: dict, pdf: Path, span: str,
                from_addr: str,
                missing: Optional[List[str]] = None) -> EmailMessage:
    """The reply, threaded under `original` and carrying `pdf`. Pure —
    offline-testable, and nothing here touches a network."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(original["to"])
    if original["cc"]:
        msg["Cc"] = ", ".join(original["cc"])
    subj = original["subject"]
    msg["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    # Both headers: In-Reply-To is what most clients thread on, References is
    # what the rest use, and a reply missing either lands as a new thread.
    msg["In-Reply-To"] = original["message_id"]
    msg["References"] = (
        f"{original['references']} {original['message_id']}".strip()
        if original.get("references") else original["message_id"])
    miss = (MISSING_LINE.format(names=", ".join(missing)) if missing else "")
    msg.set_content(BODY.format(span=span, missing=miss))
    msg.add_attachment(pdf.read_bytes(), maintype="application",
                       subtype="pdf", filename=pdf.name)
    return msg


def captains_with_pdf(only: Optional[str] = None):
    """The captainships that HAVE a weekly dispositions section, so can have a
    PDF at all. b2b/nds knock other campaigns and have no such board."""
    out = []
    for c in config.CAPTAINS:
        if only and c.key not in {k.strip() for k in only.split(",")}:
            continue
        if "knock_dispo" in {k for _h, k in c.sections}:
            out.append(c)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="The run date whose report was sent "
                                   "(YYYY-MM-DD). Default: today.")
    ap.add_argument("--only", help="Comma-separated captain keys.")
    ap.add_argument("--send", action="store_true",
                    help="Actually send. Without it this is a dry run and "
                         "prints the recipients it WOULD answer.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    from automations.captainship_drafts import weekly_pdf as WP
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, app_password)

    targets = captains_with_pdf(args.only)
    if not targets:
        print("no captainship with a weekly dispositions section matched")
        return 1
    try:
        pw = app_password()
    except Exception as e:  # noqa: BLE001
        print(f"✗ no app password available: {e}")
        return 1

    sat = WP.last_report_saturday(today)
    span = WP._span(sat)
    sent_n = skipped = 0
    for c in targets:
        subject = config.subject_for(c, today)
        # BUILD from the boards on disk rather than trusting whatever PDF is
        # already there. weekly_pdf.build re-prints when the PNGs exist, which
        # is the whole point today: Rafael's file on the mini was printed at
        # 12:55, BEFORE the column changes, and mailing it would have answered
        # his request with the layout he asked us to change.
        built = WP.build(c, today, config.RENDER_DIR)
        if not built:
            print(f"  ⤳ {c.key}: no boards for week ending {sat} — SKIPPED")
            skipped += 1
            continue
        pdf = Path(built[0])
        if not (pdf.exists() and pdf.stat().st_size):
            print(f"  ⤳ {c.key}: PDF did not print — SKIPPED")
            skipped += 1
            continue
        original = find_sent(subject, FROM_ADDR, pw)
        if not original:
            print(f"  ⤳ {c.key}: no sent message titled {subject!r} — SKIPPED")
            skipped += 1
            continue
        gaps = missing_offices(config.RENDER_DIR, c.key, sat)
        reply = build_reply(original, pdf, span, FROM_ADDR, missing=gaps)
        who = original["to"] + original["cc"]
        if gaps:
            print(f"      ⚠ {len(gaps)} office(s) missing from the PDF: "
                  f"{', '.join(gaps)}")
        print(f"  {c.key}: reply to {len(who)} recipient(s) "
              f"[{', '.join(who[:3])}{', …' if len(who) > 3 else ''}] "
              f"+ {pdf.name} ({pdf.stat().st_size // 1024} KB)")
        if not args.send:
            continue
        from automations.captainship_drafts import mailer
        mailer.send_one(reply)
        print(f"    ✓ sent")
        sent_n += 1

    if not args.send:
        print("\n--dry-run (default): nothing was sent. Add --send to mail.")
    else:
        print(f"\n✓ {sent_n} reply(ies) sent, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
