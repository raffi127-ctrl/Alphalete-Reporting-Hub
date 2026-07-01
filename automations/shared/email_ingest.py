"""Generic IMAP attachment fetcher for the reporting inbox.

Reads alphaletereporting@gmail.com (the reporting account, NOT raffi127) over
IMAP with the stored Gmail app password — the same credential the scheduled
reports use. Generalizes residential_rep_count/email_source.py so any
email-fed report can pull its source file(s) unattended: pass the sender +
which attachment filename patterns to grab.

The source emails get foldered, so we always search '[Gmail]/All Mail'. Read
is done readonly (never marks mail read or moves it).
"""
from __future__ import annotations

import datetime as dt
import email
import fnmatch
import imaplib
import re
from email.header import decode_header
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

IMAP_HOST = "imap.gmail.com"
ACCOUNT = "alphaletereporting@gmail.com"
APP_PW_PATH = Path.home() / ".config" / "recruiting-report" / "gmail-app-password"


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
    """Attachment filename, whitespace-normalized. Email header folding can
    inject newlines into a long filename ('Coel\\n Reif_….xlsx'), which breaks
    dedup AND the on-disk filename — collapse any whitespace run to one space."""
    return re.sub(r"\s+", " ", _decode(part.get_filename() or "")).strip()


def _connect() -> imaplib.IMAP4_SSL:
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(ACCOUNT, _app_password())
    M.select('"[Gmail]/All Mail"', readonly=True)
    return M


def _search(M, sender: str, subject: Optional[str], since_days: int) -> List[bytes]:
    crit = f'(FROM "{sender}"'
    if subject:
        crit += f' SUBJECT "{subject}"'
    since = (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
    crit += f' SINCE {since})'
    typ, data = M.search(None, crit)
    return (data[0] or b"").split()


def fetch_by_globs(
    sender: str,
    filename_globs: Iterable[str],
    dest_dir: str | Path,
    *,
    subject: Optional[str] = None,
    since_days: int = 60,
    verbose: bool = True,
) -> Dict[str, Path]:
    """Download the NEWEST attachment matching each of `filename_globs`
    (case-insensitive fnmatch) sent FROM `sender` (optionally narrowed to a
    `subject` substring), into `dest_dir`.

    Returns {glob: saved_path} for the globs that matched. A glob with no
    matching email is simply ABSENT from the result — partial-safe, so the
    caller decides whether a missing file is OK (Frontier) or a hard fail.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    globs = list(filename_globs)
    found: Dict[str, Path] = {}
    M = _connect()
    try:
        for i in reversed(_search(M, sender, subject, since_days)):   # newest first
            if len(found) == len(globs):
                break
            _, raw = M.fetch(i, "(RFC822)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            for part in msg.walk():
                fn = _filename(part)
                if not fn:
                    continue
                for g in globs:
                    if g in found:
                        continue
                    if fnmatch.fnmatch(fn.lower(), g.lower()):
                        out = dest / fn
                        out.write_bytes(part.get_payload(decode=True))
                        found[g] = out
                        if verbose:
                            print(f"  ✓ {g}  ->  {fn}", flush=True)
        return found
    finally:
        M.logout()


def fetch_all(
    sender: str,
    filename_globs: Iterable[str],
    dest_dir: str | Path,
    *,
    subject: Optional[str] = None,
    since_days: int = 60,
    verbose: bool = True,
) -> List[Path]:
    """Download EVERY attachment matching any of `filename_globs` FROM `sender`
    in the window, deduped by filename (newest email wins on a resend). For
    reports whose source is MANY files — e.g. one financial workbook per owner —
    rather than one-per-type. `sender` may be a bare domain ("hubtruth.com") to
    match every address at it. Returns the saved paths."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    globs = list(filename_globs)
    seen: Dict[str, Path] = {}      # filename -> path; newest-first, first wins
    M = _connect()
    try:
        for i in reversed(_search(M, sender, subject, since_days)):   # newest first
            _, raw = M.fetch(i, "(RFC822)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            for part in msg.walk():
                fn = _filename(part)
                if not fn or fn in seen:
                    continue
                if any(fnmatch.fnmatch(fn.lower(), g.lower()) for g in globs):
                    out = dest / fn
                    out.write_bytes(part.get_payload(decode=True))
                    seen[fn] = out
                    if verbose:
                        print(f"  ✓ {fn}", flush=True)
        return list(seen.values())
    finally:
        M.logout()


def list_matches(
    sender: str,
    filename_globs: Iterable[str],
    *,
    subject: Optional[str] = None,
    since_days: int = 60,
) -> Dict[str, Tuple[str, str]]:
    """Cheap probe (no body download): for each glob, the newest matching
    attachment's (filename, email_date). Used by the readiness gate to confirm
    this period's files have landed before running. Returns {glob: (fn, date)}.
    """
    globs = list(filename_globs)
    out: Dict[str, Tuple[str, str]] = {}
    M = _connect()
    try:
        for i in reversed(_search(M, sender, subject, since_days)):
            if len(out) == len(globs):
                break
            _, raw = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (DATE)] BODYSTRUCTURE)")
            blob = b""
            for part in (raw or []):
                if isinstance(part, tuple):
                    blob += (part[0] or b"") + (part[1] or b"")
                elif isinstance(part, (bytes, bytearray)):
                    blob += bytes(part)
            text = blob.decode("utf-8", "replace")
            import re
            date = ""
            dm = re.search(r"Date:\s*(.*)", text, re.I)
            if dm:
                date = dm.group(1).strip()[:16]
            for fn in re.findall(r'"([^"]+\.(?:xlsx|pdf|csv))"', text, re.I):
                for g in globs:
                    if g not in out and fnmatch.fnmatch(fn.lower(), g.lower()):
                        out[g] = (fn, date)
        return out
    finally:
        M.logout()
