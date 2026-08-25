"""The roster's three buckets, and the guard that keeps a re-run cheap.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.digi_docs.test_roster
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.digi_docs import roster


HEADER = ["#", "2ND Round Interviewer", "Trainer", "Name", "Last Name",
          "Contact Added", "Email", "Phone", "Location", "Final Status",
          "BG Status : Last Checked", "Digi Docs", "Onboarding Quizzes",
          "Blue Ink", "Headshot Photo", "Friday Confirmation"]


# Default to somebody who SHOWED UP. Every fixture that isn't specifically
# testing the no-show rule needs a showed-up signal, or the rule correctly
# drops it and the test ends up asserting about an empty list.
def _row(n, first, last, *, final="Showed Up To CR", bg="Passed",
         friday="Confirmed: OTP", digi="FALSE"):
    r = [""] * len(HEADER)
    r[0], r[3], r[4] = str(n), first, last
    r[6] = f"{first.lower()}@example.com"
    r[9], r[10], r[11], r[15] = final, bg, digi, friday
    return r


class TheThreeBuckets(unittest.TestCase):
    """Everyone lands in exactly one, and they add up to the tab."""

    def setUp(self):
        self.values = [
            ["WEEK OF 8.24"],
            HEADER,
            _row(1, "Angelica", "Pedroza"),                       # send
            _row(2, "Carol", "Pena", digi="TRUE"),                # done by hand
            _row(3, "Melissa", "Soto", final="Terminated"),       # not starting
        ]
        self.cands = roster.candidates(self.values, "D2D OBCL 8.24")

    def test_everyone_is_accounted_for(self):
        send = roster.to_send(self.cands)
        done = roster.done_by_hand(self.cands)
        skip = [c for c in self.cands if not c.eligible]
        self.assertEqual(len(send) + len(done) + len(skip), len(self.cands))

    def test_a_hand_ticked_rep_is_not_sent_again(self):
        self.assertNotIn("Carol Pena",
                         [c.name for c in roster.to_send(self.cands)])
        self.assertIn("Carol Pena",
                      [c.name for c in roster.done_by_hand(self.cands)])

    def test_someone_who_isnt_starting_is_neither_sent_nor_counted_done(self):
        """Terminated must not quietly land in the 'already handled' bucket --
        that would read as work finished rather than work correctly skipped."""
        self.assertNotIn("Melissa Soto",
                         [c.name for c in roster.to_send(self.cands)])
        self.assertNotIn("Melissa Soto",
                         [c.name for c in roster.done_by_hand(self.cands)])

    def test_the_digi_docs_column_is_found_by_label(self):
        c = next(c for c in self.cands if c.name == "Angelica Pedroza")
        self.assertEqual(c.digi_col, HEADER.index("Digi Docs") + 1)
        self.assertEqual(c.digi_val, "FALSE")


class TwoChartsOnOneTab(unittest.TestCase):
    """Monday's tab carries two charts. The second one's columns are read from
    the second one's HEADER -- if they were read from the first, a chart whose
    columns sit anywhere else gets written in the wrong place."""

    def test_the_second_chart_uses_its_own_header(self):
        shifted = ["SPACER"] + HEADER          # same labels, all one to the right
        values = [
            ["WEEK OF 8.24"],
            HEADER,
            _row(1, "Angelica", "Pedroza"),
            [""],
            ["WEEK OF 8.31"],
            shifted,
            [""] + _row(2, "Ayden", "Nyanasimeibi"),
        ]
        cands = roster.candidates(values, "D2D OBCL 8.24")
        first = next(c for c in cands if c.name == "Angelica Pedroza")
        second = next(c for c in cands if c.name == "Ayden Nyanasimeibi")
        self.assertEqual(first.digi_col, HEADER.index("Digi Docs") + 1)
        self.assertEqual(second.digi_col, shifted.index("Digi Docs") + 1)
        self.assertNotEqual(first.digi_col, second.digi_col)


class TheDayOneNoShowRule(unittest.TestCase):
    """No "showed up" marking and no location, once the chart's date has passed,
    means nobody ever saw them (Megan 2026-08-25).

    Distinct from blueink's block-list, which names explicit bad outcomes. A
    no-show leaves NO outcome -- two empty cells -- so the block-list passes
    them straight through. Without this, contracts go to people who never came.
    """

    def _cands(self, today):
        values = [["WEEK OF 8.24"], HEADER,
                  _row(1, "Ignacio", "Lara", final="Showed Up To CR"),
                  _row(2, "Angelica", "Pedroza", final=""),   # no status, no loc
                  _row(3, "Carol", "Pena", final="")]
        values[4][8] = "Dallas"                            # location only
        return roster.candidates(values, "D2D OBCL 8.24", today=today)

    def test_blank_status_and_blank_location_is_a_no_show(self):
        c = self._cands(dt.date(2026, 8, 25))
        by = {x.name: x for x in c}
        self.assertTrue(by["Angelica Pedroza"].no_show)

    def test_a_no_show_is_still_sent_to(self):
        """The flag REPORTS, it does not gate. We send Monday 7:45am, before
        anyone has shown up -- gating on it would send to almost nobody, and
        withholding documents from someone who does start costs them their first
        day (Megan 2026-08-25: "these will send to everyone on the OBCL that's
        scheduled to start. But they may not show.")."""
        c = self._cands(dt.date(2026, 8, 25))
        by = {x.name: x for x in c}
        self.assertTrue(by["Angelica Pedroza"].no_show)
        self.assertTrue(by["Angelica Pedroza"].eligible)
        self.assertIn("Angelica Pedroza",
                      [x.name for x in roster.to_send(c)])

    def test_either_signal_alone_is_enough_to_count_as_showed_up(self):
        c = self._cands(dt.date(2026, 8, 25))
        by = {x.name: x for x in c}
        self.assertFalse(by["Ignacio Lara"].no_show)   # status only
        self.assertFalse(by["Carol Pena"].no_show)     # location only

    def test_nobody_is_a_no_show_before_the_chart_date_passes(self):
        """On or before the date, blank cells just mean the day has not happened
        -- judging then would skip the entire week."""
        c = self._cands(dt.date(2026, 8, 24))
        self.assertEqual([x.name for x in c if x.no_show], [])


class TheColumnCanBeMissing(unittest.TestCase):
    def test_no_column_does_not_hold_the_send_back(self):
        """Paperwork beats a marking -- blueink_docs' rule. They still send;
        the caller warns loudly that nothing will be marked."""
        no_col = [h for h in HEADER if h != "Digi Docs"]
        values = [["WEEK OF 8.24"], no_col,
                  _row(1, "Angelica", "Pedroza")[:len(no_col)]]
        cands = roster.candidates(values, "D2D OBCL 8.24")
        self.assertEqual([c.digi_col for c in cands], [0])
        self.assertEqual(len(roster.to_send(cands)), 1)
        self.assertEqual(len(roster.missing_column(cands)), 1)


if __name__ == "__main__":
    unittest.main()
