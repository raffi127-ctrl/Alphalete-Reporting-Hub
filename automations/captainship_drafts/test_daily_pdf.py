"""The daily knock attachments: which files get made, and what the body keeps.

Rafael's 2026-09-01 ask has three halves and each can break on its own:
the weekly board must LEAVE the body without leaving the capture, the daily
boards must gain one captainship-wide PDF, and each owner must gain their own.
His worked example — 1 weekly + 1 combined + 13 owners = 15 attachments — is
the last test here, spelled out end to end.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.captainship_drafts import config, daily_pdf, email_build


def _png(path: Path, w: int = 240, h: int = 80) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (250, 250, 250)).save(path)
    return path


def _html_of(msg) -> str:
    """The message's HTML body, wherever the MIME nesting put it — the shape
    changes with how many inline images a bundle carries."""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_content()
    raise AssertionError("no text/html part")


def _rafael():
    """The REAL Rafael captain row — his 13-owner captainship is the worked
    example Rafael gave, and a stand-in class would drift from config."""
    return [c for c in config.CAPTAINS if c.key == "rafael"][0]


class DailyPdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.day = dt.date(2026, 8, 31)
        self.today = dt.date(2026, 9, 1)

    def _pairs(self, n_owners: int, missing: int = 0):
        pairs = [("Daily Summary — Aug 31", _png(self.tmp / "summary.png"))]
        for i in range(n_owners):
            png = None if i < missing else _png(self.tmp / f"o{i}.png")
            pairs.append((f"Owner {i}", png))
        return pairs

    def test_one_file_per_owner_plus_the_captainship(self):
        out = daily_pdf.build(_rafael(), self.today, self._pairs(3),
                              day=self.day, out_dir=self.tmp, logfn=lambda *_: None)
        self.assertEqual(len(out), 4)                    # 1 combined + 3 owners
        names = [n for _p, n in out]
        # Owner name FIRST (Rafael 2026-09-02): a phone truncates the tail, so
        # the half that identifies the file has to be the half that shows. The
        # captain's DISPLAY name ("Rafael") is also what keeps this file
        # distinct from his own office's page ("Rafael Hidalgo").
        self.assertEqual(
            names[0],
            "Rafael's Captainship - Daily Knocks disposition - Aug 31, 2026.pdf")
        self.assertTrue(all(n.endswith("Aug 31, 2026.pdf") for n in names))
        self.assertEqual(names[1:], [
            f"Owner {i} - Daily Knocks disposition - Aug 31, 2026.pdf"
            for i in range(3)])
        self.assertTrue(all(n.startswith(f"Owner {i}")
                            for i, n in enumerate(names[1:])))
        for p, _n in out:
            self.assertTrue(p.exists() and p.stat().st_size)

    def test_the_summary_gets_no_file_of_its_own(self):
        out = daily_pdf.build(_rafael(), self.today, self._pairs(2),
                              day=self.day, out_dir=self.tmp, logfn=lambda *_: None)
        self.assertNotIn("Daily Summary",
                         " ".join(n for _p, n in out[1:]))

    def test_an_owner_with_no_board_gets_no_page(self):
        # The body already names them in a pending note; a blank page would
        # say less than their absence from the attachment list.
        pairs = self._pairs(3, missing=1)
        pages, owners = daily_pdf.split_pages(pairs)
        self.assertEqual(len(owners), 2)
        self.assertEqual(len(pages), 3)                  # summary + 2 owners

    def test_incomplete_suffix_is_stripped_from_the_file_name(self):
        pairs = [("Daily Summary — Aug 31", _png(self.tmp / "s.png")),
                 ("Cody Cannon — ⚠ INCOMPLETE: apps unavailable",
                  _png(self.tmp / "c.png"))]
        out = daily_pdf.build(_rafael(), self.today, pairs, day=self.day,
                              out_dir=self.tmp, logfn=lambda *_: None)
        self.assertEqual(out[1][1],
                         "Cody Cannon - Daily Knocks disposition - Aug 31, 2026.pdf")

    def test_nothing_on_disk_is_not_a_failure(self):
        self.assertEqual(
            daily_pdf.build(_rafael(), self.today, [], day=self.day,
                            out_dir=self.tmp, logfn=lambda *_: None), [])

    def test_weekly_section_left_the_body_but_not_the_capture(self):
        cap, sunday = _rafael(), dt.date(2026, 9, 6)
        self.assertIn("knock_dispo", [k for _h, k in cap.sections_on(sunday)])
        self.assertNotIn("knock_dispo",
                         [k for _h, k in cap.body_sections_on(sunday)])
        # …and the daily section stays in the body (§10 is Rafael's reference
        # for what the combined PDF should look like).
        self.assertIn("daily_knocks",
                      [k for _h, k in cap.body_sections_on(sunday)])

    def test_rafaels_worked_example_is_fifteen_attachments(self):
        pairs = self._pairs(13)
        dailies = daily_pdf.build(_rafael(), self.today, pairs, day=self.day,
                                  out_dir=self.tmp, logfn=lambda *_: None)
        weekly = (_png(self.tmp / "weekly.png"), "Weekly - Aug 24-29, 2026.pdf")
        bundle = {"daily_knocks": pairs, "daily_pdfs": dailies,
                  "weekly_pdf": weekly, "errors": {}}
        msg = email_build.build(_rafael(), bundle, self.today)
        attached = [p.get_filename() for p in msg.iter_attachments()
                    if p.get_filename()]
        self.assertEqual(len(attached), 15)
        self.assertEqual(attached[0], weekly[1])
        self.assertIn("Captainship", attached[1])
        self.assertEqual(len(attached[2:]), 13)

    def test_the_weekly_board_is_no_longer_in_the_body_html(self):
        pairs = self._pairs(2)
        bundle = {"daily_knocks": pairs,
                  "knock_dispo": [("Captainship Summary",
                                   _png(self.tmp / "w.png"))],
                  "errors": {}}
        msg = email_build.build(_rafael(), bundle, dt.date(2026, 9, 6))  # Sunday
        html = _html_of(msg)
        self.assertIn("Daily Knocks", html)
        self.assertNotIn("Weekly Knock Dispositions", html)


if __name__ == "__main__":
    unittest.main()


class AttachmentLimitTests(unittest.TestCase):
    """Gmail's 25MB is a cliff, not a slope — a message past it FAILS. Every
    page keeps the standard width (Eve 2026-09-01: legibility first), so the
    per-owner copies, which are the same boards a third time, are the only
    thing that can give way — and only when the assembled message really would
    not send."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _file(self, name: str, size: int) -> Path:
        p = self.tmp / name
        p.write_bytes(b"0" * size)
        return p

    def _bundle(self, owner_sizes, weekly=200_000, combined=200_000):
        dailies = [(self._file("combined.pdf", combined),
                    "Raf's Captainship - Daily Knocks disposition - Aug 31, 2026.pdf")]
        for i, sz in enumerate(owner_sizes):
            dailies.append((self._file(f"o{i}.pdf", sz),
                            f"Owner {i} - Daily Knocks disposition - Aug 31, 2026.pdf"))
        return {"weekly_pdf": (self._file("weekly.pdf", weekly),
                               "Weekly - Aug 24-29, 2026.pdf"),
                "daily_pdfs": dailies, "daily_knocks": [], "errors": {}}

    def _names(self, msg):
        return [p.get_filename() for p in msg.iter_attachments()
                if p.get_filename()]

    def test_a_normal_report_keeps_every_owner(self):
        msg = email_build.build(_rafael(), self._bundle([200_000] * 13),
                                dt.date(2026, 9, 1))
        self.assertEqual(len(self._names(msg)), 15)
        self.assertNotIn("left off to keep this email", _html_of(msg))

    def test_only_the_per_owner_copies_give_way(self):
        big = email_build.MAX_MESSAGE_BYTES // 3
        msg = email_build.build(_rafael(), self._bundle([big] * 8),
                                dt.date(2026, 9, 1))
        names = self._names(msg)
        self.assertLess(len(names), 10)
        self.assertIn("Weekly", names[0])            # never dropped
        self.assertIn("Captainship", names[1])       # never dropped

    def test_the_body_names_what_was_left_off(self):
        big = email_build.MAX_MESSAGE_BYTES // 2
        msg = email_build.build(_rafael(), self._bundle([big, big]),
                                dt.date(2026, 9, 1))
        html = _html_of(msg)
        self.assertIn("left off to keep this email under the mail size limit",
                      html)
        self.assertIn("Owner 1", html)
        # …and the note sits with the report, above the signature.
        self.assertLess(html.index("left off"), html.index("Kind regards"))

    def test_every_page_keeps_the_standard_width(self):
        # The one knob nobody may turn per report (Eve 2026-09-01).
        from automations.captainship_drafts import pdf_pages
        self.assertEqual(pdf_pages.PAGE_MAX_PX, 1800)
        self.assertFalse(hasattr(pdf_pages, "DAILY_MAX_PX"))
