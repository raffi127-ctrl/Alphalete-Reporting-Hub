#!/usr/bin/env python3
"""Read a phone number out of a DOWNLOADED resume / original message.

WHY (Carlos, 2026-08-27): "when you open a resume and the webpage comes up
blank, but you see something that says 'Download original message' or something
of the sort, you can click that download thing. That should download the resume,
and you can open up that download. That has a phone number. If that doesn't
work, then just leave it there. Don't remove that applicant."

So a blank viewer page with a download affordance is NOT a resume that has no
number — it is a resume we have not read yet. The in-page reader
(`lookup_resume_phone`) sees an empty body and, before this, called that
"confirmed uncontactable", which is exactly the verdict that gets an applicant
removed. This module is the second attempt, and its failure is deliberately
reported as BLOCKED (retryable, applicant stays) rather than as an empty resume.

Everything here except `download_and_read_phone` is a pure function of a file
path, so the parsing is unit-tested without a browser (test_resume_download.py).
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import os
import re
import subprocess
import tempfile
import zipfile

# Same shape the in-page reader uses, so both paths agree on what a phone is.
PHONE_RE = re.compile(r"\+?1?[\s\-.]*\(?\d{3}\)?[\s\-.]*\d{3}[\s\-.]*\d{4}")

# Numbers that are never an applicant's cell. An Indeed "original message" is a
# real email with Indeed's own branding and footers in it, so first-match-from-top
# can otherwise hand back a support line and we would text the wrong person —
# worse than finding nothing, because it looks like success.
_TOLLFREE = {"800", "833", "844", "855", "866", "877", "888"}

# Link text that means "give me the raw item" on the Indeed/AppStream viewers.
DOWNLOAD_RE = re.compile(
    r"download\s+(original|the\s+original|message|resume|attachment|file)"
    r"|download\s+original\s+message|^\s*download\s*$", re.I)


def looks_like_real_phone(raw: str) -> bool:
    """True for a plausible applicant number: 10 digits (or 11 leading 1), not
    toll-free, not a single repeated digit, area code not starting 0/1."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        return False
    if d[:3] in _TOLLFREE:
        return False
    if d[0] in "01":
        return False
    if len(set(d)) <= 2:            # 0000000000, 1231231231-style junk
        return False
    return True


def phone_from_text(text: str):
    """First plausible phone in `text`, reading top-down.

    Top-down on purpose: a resume header carries the applicant's own number,
    while the work-history further down carries former employers' numbers."""
    for m in PHONE_RE.finditer(text or ""):
        if looks_like_real_phone(m.group(0)):
            return m.group(0).strip()
    return None


# --------------------------------------------------------------------------- #
# Per-format text extraction
# --------------------------------------------------------------------------- #
def _text_from_pdf(path: str) -> str:
    try:
        import fitz                     # PyMuPDF
        with fitz.open(path) as doc:
            return "\n".join(p.get_text() for p in doc)
    except Exception:                   # noqa: BLE001 — try the other parser
        pass
    try:
        from pdfminer.high_level import extract_text
        return extract_text(path) or ""
    except Exception:                   # noqa: BLE001
        return ""


def _text_from_docx(path: str) -> str:
    """docx is a zip of XML — no third-party dependency needed."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", " ", xml)
    except Exception:                   # noqa: BLE001
        return ""


def _text_from_textutil(path: str) -> str:
    """macOS built-in: handles .doc/.rtf/.html/.txt/.odt without a dependency."""
    try:
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
                           capture_output=True, timeout=30)
        return (r.stdout or b"").decode("utf-8", "replace")
    except Exception:                   # noqa: BLE001
        return ""


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", s)
    return re.sub(r"<[^>]+>", " ", s)


def _text_from_eml(path: str) -> str:
    """An .eml is the original application email. The number can be in the body
    OR inside an attached resume, so walk the parts and recurse into attachments."""
    import email
    from email import policy
    try:
        with open(path, "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=policy.default)
    except Exception:                   # noqa: BLE001
        return ""
    chunks = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = (part.get_content_type() or "").lower()
        fname = part.get_filename() or ""
        try:
            payload = part.get_payload(decode=True)
        except Exception:               # noqa: BLE001
            continue
        if payload is None:
            continue
        if ctype.startswith("text/"):
            txt = payload.decode(part.get_content_charset() or "utf-8", "replace")
            chunks.append(_strip_html(txt) if "html" in ctype else txt)
            continue
        # An attachment — write it out and read it with its own extractor.
        ext = os.path.splitext(fname)[1].lower() or _ext_for_ctype(ctype)
        if not ext:
            continue
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            tmp.write(payload)
            tmp.close()
            chunks.append(extract_text(tmp.name))
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:           # noqa: BLE001
                pass
    return "\n".join(c for c in chunks if c)


def _ext_for_ctype(ctype: str) -> str:
    if "pdf" in ctype:
        return ".pdf"
    if "wordprocessingml" in ctype:
        return ".docx"
    if "msword" in ctype:
        return ".doc"
    if "rtf" in ctype:
        return ".rtf"
    return ""


def extract_text(path: str) -> str:
    """Text out of a downloaded file, dispatched on extension."""
    ext = os.path.splitext(path or "")[1].lower()
    if ext == ".pdf":
        return _text_from_pdf(path)
    if ext == ".docx":
        return _text_from_docx(path)
    if ext in (".eml", ".msg", ".mht", ".mhtml"):
        return _text_from_eml(path)
    if ext in (".doc", ".rtf", ".odt"):
        return _text_from_textutil(path)
    if ext in (".htm", ".html"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return _strip_html(fh.read())
        except Exception:               # noqa: BLE001
            return ""
    # .txt and anything else: read as text; harmless on binary (we just find no
    # phone and report it, which leaves the applicant alone).
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:                   # noqa: BLE001
        return ""


def phone_from_file(path: str):
    return phone_from_text(extract_text(path))


# --------------------------------------------------------------------------- #
# The browser half
# --------------------------------------------------------------------------- #
def find_download_link(pg):
    """(frame, locator) for a 'Download original message'-style control, else
    (None, None). Frames included — the viewer nests its content."""
    xp = ("xpath=//a[contains(translate(normalize-space(.),"
          "'DOWNLOAD','download'),'download')] "
          "| //button[contains(translate(normalize-space(.),"
          "'DOWNLOAD','download'),'download')]")
    for fr in ([pg] + list(getattr(pg, "frames", []) or [])):
        try:
            loc = fr.locator(xp)
            n = loc.count()
        except Exception:               # noqa: BLE001
            continue
        for i in range(min(n, 6)):
            try:
                el = loc.nth(i)
                if DOWNLOAD_RE.search((el.inner_text() or "").strip()):
                    return fr, el
            except Exception:           # noqa: BLE001
                continue
        if n:                            # a plain "Download" with odd wording
            try:
                return fr, loc.first
            except Exception:           # noqa: BLE001
                pass
    return None, None


def download_and_read_phone(pg, timeout_ms: int = 45000):
    """Click the download affordance on a blank-looking resume page, read the
    file, and return (phone, detail).

    Returns (None, detail) when there is nothing to click or nothing readable.
    The CALLER must treat every failure here as retryable — Carlos's rule is that
    an applicant we could not read is left alone, never removed."""
    fr, el = find_download_link(pg)
    if el is None:
        return None, "no download link on the page"
    try:
        with pg.expect_download(timeout=timeout_ms) as info:
            el.click(timeout=10000)
        dl = info.value
        name = dl.suggested_filename or "download"
        dest = os.path.join(tempfile.mkdtemp(prefix="oat_resume_"), name)
        dl.save_as(dest)
    except Exception as e:              # noqa: BLE001
        return None, f"download failed: {type(e).__name__}: {str(e)[:80]}"
    try:
        phone = phone_from_file(dest)
        size = os.path.getsize(dest)
    except Exception as e:              # noqa: BLE001
        return None, f"could not read {os.path.basename(dest)}: {type(e).__name__}"
    finally:
        try:
            os.unlink(dest)
        except Exception:               # noqa: BLE001
            pass
    if phone:
        return phone, f"from downloaded {name} ({size}B)"
    return None, f"downloaded {name} ({size}B) but no phone in it"
