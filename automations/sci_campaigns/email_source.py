"""Pull Adriana's weekly "Residential Telecom Tracker – RANKED" PDFs from
alphaletereporting@gmail.com over IMAP.

We read this account (NOT raffi127) with the stored Gmail app password — the
same credential every scheduled report uses. Source mail gets foldered, so we
always search '[Gmail]/All Mail', read-only.

The week is taken from the SUBJECT ('… Week Ending 7.18.2026'), never from the
calendar: the email for a Saturday week-ending normally lands the FOLLOWING
Friday, and has slipped to a Sunday more than once (WE 6.27 arrived Sun 7/5, WE
7.18 arrived Sun 7/26). Trusting the subject makes the report idempotent and
immune to a late send.
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import re
from email.header import decode_header
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

IMAP_HOST = "imap.gmail.com"
ACCOUNT = "alphaletereporting@gmail.com"
APP_PW_PATH = Path.home() / ".config" / "recruiting-report" / "gmail-app-password"
# Adriana has sent from two addresses (personal gmail through 3.28.2026, then
# her Aptel address from 5.30.2026). Match on SUBJECT only so a third address
# doesn't silently stop the report.
SUBJECT = "Residential Telecom Tracker"


class Tracker(NamedTuple):
    week_ending: dt.date          # Saturday, from the subject
    subject: str
    email_date: str
    byday_pdf: Optional[Path]     # "… - Campaign Totals By Day.pdf"
    main_pdf: Optional[Path]      # the RANKED per-office PDF

    @property
    def complete(self) -> bool:
        return bool(self.byday_pdf and self.main_pdf)


def _app_password() -> str:
    if not APP_PW_PATH.exists():
        raise RuntimeError(
            f"Gmail app password not found at {APP_PW_PATH}. This is the "
            f"app password for {ACCOUNT} — ask Megan to save it there.")
    # utf-8-sig strips a stray BOM; Gmail app passwords are shown with spaces.
    return APP_PW_PATH.read_text(encoding="utf-8-sig").strip().replace(" ", "")


def _decode(s: str) -> str:
    return "".join(
        t.decode(enc or "utf-8", "replace") if isinstance(t, bytes) else t
        for t, enc in decode_header(s or ""))


def _filename(part) -> str:
    """Attachment filename, whitespace-normalized — header folding injects
    newlines into these long names ('… By\\r\\n Day.pdf')."""
    return re.sub(r"\s+", " ", _decode(part.get_filename() or "")).strip()


def we_label(d: dt.date) -> str:
    """'7.18.2026' — Adriana's own week format, which is what Rafael/Maud/Megan
    recognise. Built by hand because '%-m' is a Mac-only strftime."""
    return f"{d.month}.{d.day}.{d.year}"


def week_from_subject(subject: str) -> Optional[dt.date]:
    """'… Week Ending 7.18.2026' -> date(2026, 7, 18).

    Replies are rejected — they quote the same subject, carry no attachments and
    would mask the real email. FORWARDS are kept: WE 5.30.2026 reached the
    reporting inbox only as Rafael's 'Fwd:', attachments intact, and dropping it
    would leave a permanent hole. fetch() still requires the PDFs, so a
    forward without them is discarded there.
    """
    if re.match(r"\s*re\s*:", subject or "", re.I):
        return None
    m = re.search(r"Week\s+Ending\s+(\d{1,2})\.(\d{1,2})\.(\d{2,4})",
                  subject or "", re.I)
    if not m:
        return None
    year = int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return dt.date(year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def _connect() -> imaplib.IMAP4_SSL:
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(ACCOUNT, _app_password())
    M.select('"[Gmail]/All Mail"', readonly=True)
    return M


def _is_byday(fn: str) -> bool:
    return fn.lower().endswith(".pdf") and "totals by day" in fn.lower()


def _is_main(fn: str) -> bool:
    return fn.lower().endswith(".pdf") and "totals by day" not in fn.lower()


def available_weeks(since_days: int = 400) -> Dict[dt.date, str]:
    """Cheap probe (headers only, no attachment bodies): {week_ending: subject}
    for every tracker email in the window. Used by the readiness gate and by
    --list, and by run.py to decide which weeks a backfill can cover."""
    since = (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
    M = _connect()
    out: Dict[dt.date, str] = {}
    try:
        typ, data = M.search(None, f'(SUBJECT "{SUBJECT}" SINCE {since})')
        for i in (data[0] or b"").split():
            _, raw = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
            blob = b"".join(p[1] for p in raw if isinstance(p, tuple))
            subj = _decode(blob.decode("utf-8", "replace")
                           .split(":", 1)[-1].strip())
            we = week_from_subject(subj)
            if we:
                out[we] = subj
        return out
    finally:
        M.logout()


def latest_week_ending(since_days: int = 400) -> Optional[dt.date]:
    """The newest week-ending Adriana has sent. None if nothing in the window."""
    weeks = available_weeks(since_days)
    return max(weeks) if weeks else None


def fetch(dest_dir: str | Path, weeks: Optional[List[dt.date]] = None,
          *, since_days: int = 400, verbose: bool = True) -> List[Tracker]:
    """Download both PDFs for `weeks` (or for EVERY tracker email in the window
    when weeks is None), into `dest_dir`. Returns Trackers OLDEST->NEWEST so a
    backfill writes weeks in chronological order.

    A week whose email exists but is missing one of the two PDFs still comes
    back (with that field None) — the caller decides. `.complete` says which.
    On a resend, the NEWEST email for a week wins.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    want = set(weeks) if weeks else None
    since = (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
    found: Dict[dt.date, Tracker] = {}
    M = _connect()
    try:
        # reversed = newest first, so the first email seen for a week wins.
        typ, data = M.search(None, f'(SUBJECT "{SUBJECT}" SINCE {since})')
        for i in reversed((data[0] or b"").split()):
            if want is not None and want.issubset(found):
                break
            _, raw = M.fetch(i, "(RFC822)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            subj = _decode(msg.get("Subject") or "")
            we = week_from_subject(subj)
            if we is None or we in found or (want is not None and we not in want):
                continue
            byday = main = None
            for part in msg.walk():
                fn = _filename(part)
                if not fn:
                    continue
                if _is_byday(fn) and byday is None:
                    byday = dest / f"{we:%Y-%m-%d}_byday.pdf"
                    byday.write_bytes(part.get_payload(decode=True))
                elif _is_main(fn) and main is None:
                    main = dest / f"{we:%Y-%m-%d}_main.pdf"
                    main.write_bytes(part.get_payload(decode=True))
            if byday is None and main is None:
                continue          # a thread reply with no attachments
            found[we] = Tracker(we, subj, msg.get("Date") or "", byday, main)
            if verbose:
                have = "+".join(n for n, p in
                                (("byday", byday), ("main", main)) if p)
                print(f"  ✓ WE {we_label(we)}  ({have})", flush=True)
    finally:
        M.logout()
    return [found[w] for w in sorted(found)]
