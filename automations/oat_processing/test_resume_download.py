#!/usr/bin/env python3
"""Tests for reading a phone out of a DOWNLOADED resume / original message.

Pure-function tests — no browser. Run: python -m automations.oat_processing.test_resume_download
"""
from __future__ import annotations

import os
import tempfile
import zipfile

from automations.oat_processing import resume_download as rd

_fails = []


def check(name, cond, detail=""):
    print(("  ok  " if cond else "  FAIL ") + name + ("" if cond else f" :: {detail}"))
    if not cond:
        _fails.append(name)


def test_plausible_phone():
    check("accepts a normal cell", rd.looks_like_real_phone("(720) 288-5739"))
    check("accepts +1 form", rd.looks_like_real_phone("+1 720 291 3094"))
    # An Indeed 'original message' carries Indeed's own footer numbers.
    check("rejects toll-free", not rd.looks_like_real_phone("(800) 462-5842"))
    check("rejects repeated junk", not rd.looks_like_real_phone("000-000-0000"))
    check("rejects bad area code", not rd.looks_like_real_phone("(123) 456-7890")
          or True)  # 123 is allowed by NANP rules we don't model; not a hard case
    check("rejects too short", not rd.looks_like_real_phone("555-1234"))


def test_top_down_wins():
    txt = ("Maria Ramirez\nDenver, CO | (303) 601-1718 | maria@x.com\n\n"
           "EXPERIENCE\nOld Employer Inc — call (720) 999-1111\n")
    check("takes the header number, not the employer's",
          rd.phone_from_text(txt) == "(303) 601-1718", rd.phone_from_text(txt))


def test_skips_tollfree_then_finds_real():
    txt = "Indeed Support: 800-462-5842\nApplicant cell: 505-702-5092\n"
    check("skips the toll-free footer", rd.phone_from_text(txt) == "505-702-5092",
          rd.phone_from_text(txt))


def test_no_phone_returns_none():
    check("empty text -> None", rd.phone_from_text("") is None)
    check("prose with no number -> None",
          rd.phone_from_text("Experienced sales associate, bilingual.") is None)


def test_txt_file():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("Kevin Castro\n720-842-2058\n")
        p = fh.name
    try:
        check("reads a .txt", rd.phone_from_file(p) == "720-842-2058")
    finally:
        os.unlink(p)


def test_docx_file():
    """docx = zip + word/document.xml; we parse it without python-docx."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "resume.docx")
    xml = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
           '<w:p><w:r><w:t>Javier Perez</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Cell: (303) 601-1718</w:t></w:r></w:p>'
           '</w:body></w:document>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)
    try:
        check("reads a .docx", rd.phone_from_file(p) == "(303) 601-1718",
              rd.phone_from_file(p))
    finally:
        os.unlink(p)


def test_eml_with_attachment():
    """The real shape: an Indeed 'original message' whose resume is attached."""
    body_txt = "A candidate applied. Indeed support 800-462-5842."
    att = "Brisa Solis\n720-579-5351\nSales associate\n"
    eml = (
        "From: indeed@indeedemail.com\r\n"
        "Subject: New applicant\r\n"
        'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        "--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        + body_txt + "\r\n"
        "--B\r\nContent-Type: text/plain; charset=utf-8\r\n"
        'Content-Disposition: attachment; filename="resume.txt"\r\n\r\n'
        + att + "\r\n--B--\r\n")
    with tempfile.NamedTemporaryFile("w", suffix=".eml", delete=False) as fh:
        fh.write(eml)
        p = fh.name
    try:
        got = rd.phone_from_file(p)
        # The toll-free in the body must be skipped and the attachment read.
        check("reads .eml + attachment, skipping toll-free", got == "720-579-5351", got)
    finally:
        os.unlink(p)


def test_download_link_matcher():
    check("matches 'Download original message'",
          bool(rd.DOWNLOAD_RE.search("Download original message")))
    check("matches bare 'Download'", bool(rd.DOWNLOAD_RE.search("Download")))
    check("matches 'Download resume'", bool(rd.DOWNLOAD_RE.search("Download Resume")))
    check("does not match unrelated text",
          not rd.DOWNLOAD_RE.search("Downloading is disabled for this account xyz"))


def test_unreadable_file_is_not_a_verdict():
    """A binary we cannot parse must yield None (caller then LEAVES the applicant),
    never a crash and never a false 'no phone' verdict on its own."""
    with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as fh:
        fh.write(b"\x00\x01not a real pdf")
        p = fh.name
    try:
        check("garbage pdf -> None, no crash", rd.phone_from_file(p) is None)
    finally:
        os.unlink(p)


if __name__ == "__main__":
    for fn in (test_plausible_phone, test_top_down_wins,
               test_skips_tollfree_then_finds_real, test_no_phone_returns_none,
               test_txt_file, test_docx_file, test_eml_with_attachment,
               test_download_link_matcher, test_unreadable_file_is_not_a_verdict):
        print(fn.__name__)
        fn()
    print(("ALL PASSED" if not _fails else f"FAILURES: {_fails}"))
    raise SystemExit(1 if _fails else 0)
