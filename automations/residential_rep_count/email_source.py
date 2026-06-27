"""Pull Archey's weekly "Residential Rep Counts" email + attachment from
alphaletereporting@gmail.com over IMAP.

We read this account (NOT raffi127) with the stored Gmail app password — the
same credential the scheduled report uses. The source emails are organized into
custom IMAP folders, so we always search '[Gmail]/All Mail'.
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import re
from email.header import decode_header
from pathlib import Path
from typing import Optional, Tuple

IMAP_HOST = "imap.gmail.com"
ACCOUNT = "alphaletereporting@gmail.com"
APP_PW_PATH = Path.home() / ".config" / "recruiting-report" / "gmail-app-password"
SENDER = "rarchey@thesmartcircle.com"
SUBJECT = "Residential Rep Counts"


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


def _week_from_filename(fn: str) -> Optional[dt.date]:
    """Attachment is 'Residential Rep Count WE 2026-06-20 values.xlsx'."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", fn)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def fetch_latest(
    dest_dir: str | Path,
    week_ending: Optional[dt.date] = None,
) -> Tuple[Path, dt.date, str]:
    """Download the .xlsx from the most recent Archey "Residential Rep Counts"
    email (or the one matching `week_ending`, a Saturday date). Returns
    (saved_xlsx_path, week_ending_date, subject).

    Raises RuntimeError if no matching email/attachment is found — the caller
    treats that as "this week hasn't landed yet, don't write stale data".
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(ACCOUNT, _app_password())
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        typ, data = M.search(
            None, f'(FROM "{SENDER}" SUBJECT "{SUBJECT}")')
        ids = data[0].split()
        if not ids:
            raise RuntimeError(
                f"No '{SUBJECT}' emails from {SENDER} found in {ACCOUNT}.")
        # Newest first; pick the matching week (or the latest with an xlsx).
        for i in reversed(ids):
            _, raw = M.fetch(i, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])
            for part in msg.walk():
                fn = _decode(part.get_filename() or "")
                if not fn.lower().endswith(".xlsx"):
                    continue
                we = _week_from_filename(fn)
                if week_ending and we != week_ending:
                    continue
                out = dest / fn
                out.write_bytes(part.get_payload(decode=True))
                return out, we, _decode(msg.get("Subject") or "")
        raise RuntimeError(
            "Found Archey emails but no matching .xlsx attachment"
            + (f" for week ending {week_ending}." if week_ending else "."))
    finally:
        M.logout()


def fetch_recent(dest_dir: str | Path, n: int) -> list:
    """Download the .xlsx from the most recent `n` distinct-week Archey emails.
    Returns [(path, week_ending, subject)] OLDEST→NEWEST (so a backfill writes
    weeks in chronological order)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(ACCOUNT, _app_password())
    out: list = []
    seen: set = set()
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        typ, data = M.search(None, f'(FROM "{SENDER}" SUBJECT "{SUBJECT}")')
        ids = data[0].split()
        for i in reversed(ids):              # newest first
            if len(seen) >= n:
                break
            _, raw = M.fetch(i, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])
            for part in msg.walk():
                fn = _decode(part.get_filename() or "")
                if not fn.lower().endswith(".xlsx"):
                    continue
                we = _week_from_filename(fn)
                if we is None or we in seen:
                    continue
                seen.add(we)
                p = dest / fn
                p.write_bytes(part.get_payload(decode=True))
                out.append((p, we, _decode(msg.get("Subject") or "")))
                break
    finally:
        M.logout()
    return sorted(out, key=lambda t: t[1])   # oldest -> newest


def latest_week_ending() -> Optional[dt.date]:
    """Cheap probe: the Saturday week-ending of the newest Archey email
    (read from its attachment filename), without downloading the file body."""
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(ACCOUNT, _app_password())
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        typ, data = M.search(None, f'(FROM "{SENDER}" SUBJECT "{SUBJECT}")')
        ids = data[0].split()
        for i in reversed(ids):
            _, raw = M.fetch(i, "(BODY[HEADER.FIELDS (SUBJECT)])")
            subj = _decode(raw[0][1].decode("utf-8", "replace"))
            m = re.search(r"WE\s+(\d{1,2})/(\d{1,2})", subj)
            if m:
                # subject has no year; infer from today.
                today = dt.date.today()
                return _nearest_saturday(int(m.group(1)), int(m.group(2)), today)
        return None
    finally:
        M.logout()


def _nearest_saturday(month: int, day: int, ref: dt.date) -> dt.date:
    """Resolve a month/day (no year) to the closest year around `ref`."""
    for yr in (ref.year, ref.year - 1, ref.year + 1):
        try:
            d = dt.date(yr, month, day)
        except ValueError:
            continue
        if abs((d - ref).days) <= 200:
            return d
    return dt.date(ref.year, month, day)
