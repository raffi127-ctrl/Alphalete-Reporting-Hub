"""Read the PICTURE, not just the data behind it.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_rendered_dates

WHY (2026-08-26). Every other gate in this pipeline checks the data feed. None of
them looks at the PNG that actually reaches the channel. quantum_fiber happened
to be catchable from its data (its workbook publishes a refresh date), but a
board whose data is current and whose VIEW is stuck on last week — a leaked saved
view, a re-pinned week filter, both of which have bitten this repo before — is
invisible to all of them.

So the capture now records the dates the rendered dashboard displays, using the
same in-iframe leaf-text read the crop probe already does, and compares the
newest one against the day the board should cover.

WATCHING, NOT HOLDING. Nothing is withheld on this signal yet. The rule is sound
on the four boards read off the 8/26 PNGs, but it has not been through a
month-end, a Monday rollover, or the six boards nobody has sampled, and a false
hold costs 15 channels a real board — strictly worse than the miss it prevents.
The withhold machinery is already there when we trust it.

The three label shapes below are REAL, transcribed from the 8/26 boards.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.tableau_screenshots import capture as cap
from automations.tableau_screenshots import run as run_mod


class ParseRenderedDatesTest(unittest.TestCase):

    YEAR = 2026

    def test_day_columns(self):
        """att_country / b2b_att_country: 'Mon (08-24)  Tue (08-25)'."""
        self.assertEqual(
            [dt.date(2026, 8, 24), dt.date(2026, 8, 25)],
            cap.parse_rendered_dates("Mon (08-24) Tue (08-25) Grand Total",
                                     self.YEAR))

    def test_range_headers(self):
        """nds: 'New/Port/Air: 08/24 - 08/25'."""
        self.assertEqual(
            [dt.date(2026, 8, 24), dt.date(2026, 8, 25)],
            cap.parse_rendered_dates("New/Port/Air: 08/24 - 08/25", self.YEAR))

    def test_full_dates_keep_their_own_year(self):
        """quantum's 6-week history carries 'Order WE 8/30/2026'. The board's own
        year wins over the run's — that column is the only place some boards
        state one at all."""
        got = cap.parse_rendered_dates("Order WE 8/30/2026 8/23/2025", self.YEAR)
        self.assertIn(dt.date(2025, 8, 23), got)
        self.assertIn(dt.date(2026, 8, 30), got)

    def test_a_label_tableau_cut_off_is_not_a_date(self):
        """2026-08-31. att_country went from two day columns to seven, Tableau
        narrowed the headers to fit, and "Fri (08-28)" rendered as "Fri (08-2..".
        Reading that as August 2nd is how a board showing the correct completed
        week got reported as five days behind."""
        self.assertEqual([], cap.parse_rendered_dates("Fri (08-2..", self.YEAR))
        self.assertEqual([], cap.parse_rendered_dates("Mon (0..", self.YEAR))
        self.assertEqual([], cap.parse_rendered_dates("Sat (08-..", self.YEAR))

    def test_a_full_label_beside_a_cut_one_still_reads(self):
        """Only the truncated run is dropped — a legible date next to it stands."""
        self.assertEqual(
            [dt.date(2026, 8, 30)],
            cap.parse_rendered_dates("Sun (08-30) Mon (0..", self.YEAR))

    def test_truncation_is_reported(self):
        self.assertTrue(cap.has_truncated_dates("Mon (08-2.. Tue (08-2.."))
        self.assertFalse(cap.has_truncated_dates("Mon (08-24) Tue (08-25)"))
        self.assertFalse(cap.has_truncated_dates("Product Type (Bro.."))

    def test_junk_is_not_a_date(self):
        self.assertEqual([], cap.parse_rendered_dates("13/45 99 -- 0/0", 2026))
        self.assertEqual([], cap.parse_rendered_dates("", 2026))

    def test_a_board_with_no_labels_reads_empty(self):
        """Which must stay distinguishable from 'read a date and it was old' —
        the report skips the former and flags the latter."""
        self.assertEqual([], cap.parse_rendered_dates("Rank Reps Sales/Rep", 2026))


class ReportRenderedDatesTest(unittest.TestCase):

    TODAY = dt.date(2026, 8, 26)          # target day = Tue 8/25

    def setUp(self):
        cap.RENDERED_DATES.clear()
        cap.RENDERED_TRUNCATED.clear()
        self.addCleanup(cap.RENDERED_DATES.clear)
        self.addCleanup(cap.RENDERED_TRUNCATED.clear)
        # Never let a test reach Slack, even on the dry-run path.
        import automations.day_orchestrator.notify as _n
        real = _n.post_alert
        self.posted = []
        _n.post_alert = lambda *a, **k: self.posted.append((a, k))
        self.addCleanup(setattr, _n, "post_alert", real)

    def _caps(self, board_id="nds"):
        from automations.tableau_screenshots import pages as pg
        return [(pg.by_id(board_id), "/tmp/x.png")]

    def test_a_board_stuck_on_last_week_is_flagged(self):
        cap.RENDERED_DATES["nds"] = [dt.date(2026, 8, 17), dt.date(2026, 8, 18)]
        out = run_mod._report_rendered_dates(self.TODAY, self._caps(),
                                             dry_run=False)
        self.assertEqual(1, len(out))
        self.assertEqual(dt.date(2026, 8, 18), out[0][1])
        self.assertTrue(self.posted, "a flagged board must reach corrections")

    def test_a_current_board_is_silent(self):
        cap.RENDERED_DATES["nds"] = [dt.date(2026, 8, 24), dt.date(2026, 8, 25)]
        self.assertEqual([], run_mod._report_rendered_dates(
            self.TODAY, self._caps(), dry_run=False))
        self.assertFalse(self.posted)

    def test_a_board_showing_a_future_label_is_silent(self):
        """quantum's week-ENDING column reads 8/30 — ahead of the target, not
        behind it. Flagging that would fire every single day."""
        cap.RENDERED_DATES["nds"] = [dt.date(2026, 8, 30)]
        self.assertEqual([], run_mod._report_rendered_dates(
            self.TODAY, self._caps(), dry_run=False))

    def test_a_board_whose_labels_are_cut_off_is_never_flagged(self):
        """Unreadable is not the same claim as old. The 2026-08-31 board showed
        the right week; its headers were just too narrow to say so."""
        cap.RENDERED_DATES["nds"] = [dt.date(2026, 8, 18)]
        cap.RENDERED_TRUNCATED["nds"] = True
        self.assertEqual([], run_mod._report_rendered_dates(
            self.TODAY, self._caps(), dry_run=False))
        self.assertFalse(self.posted)

    def test_a_readable_board_is_still_flagged(self):
        """The fix must not blind the check on boards it CAN read."""
        cap.RENDERED_DATES["nds"] = [dt.date(2026, 8, 18)]
        cap.RENDERED_TRUNCATED["nds"] = False
        self.assertEqual(1, len(run_mod._report_rendered_dates(
            self.TODAY, self._caps(), dry_run=False)))
        self.assertTrue(self.posted)

    def test_a_board_we_could_not_read_is_never_flagged(self):
        """Read nothing, say nothing — the standing rule for every probe here."""
        cap.RENDERED_DATES["nds"] = []
        self.assertEqual([], run_mod._report_rendered_dates(
            self.TODAY, self._caps(), dry_run=False))
        self.assertFalse(self.posted)

    def test_it_reports_and_never_withholds(self):
        """The whole point of the current stage: flagged boards still POST."""
        cap.RENDERED_DATES["nds"] = [dt.date(2026, 8, 1)]
        caps = self._caps()
        run_mod._report_rendered_dates(self.TODAY, caps, dry_run=False)
        self.assertEqual(1, len(caps), "the capture list must be untouched")


if __name__ == "__main__":
    unittest.main()
