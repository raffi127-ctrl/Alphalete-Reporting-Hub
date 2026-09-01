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
        # The captain's DISPLAY name ("Rafael"), which is also what keeps this
        # file distinct from his own office's page ("Rafael Hidalgo").
        self.assertEqual(
            names[0],
            "Daily Knock Dispositions - Rafael's Captainship - Aug 31, 2026.pdf")
        self.assertTrue(all(n.endswith("Aug 31, 2026.pdf") for n in names))
        self.assertEqual(names[1:], [
            f"Daily Knock Dispositions - Owner {i} - Aug 31, 2026.pdf"
            for i in range(3)])
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
                         "Daily Knock Dispositions - Cody Cannon - Aug 31, 2026.pdf")

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
        html = msg.get_payload()[1].get_payload()[0].get_content()
        self.assertIn("Daily Knocks", html)
        self.assertNotIn("Weekly Knock Dispositions", html)


if __name__ == "__main__":
    unittest.main()
