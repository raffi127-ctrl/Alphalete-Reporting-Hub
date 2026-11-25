"""Never owner submitted by week three = the onboarding never finished.

Megan, 2026-11-25: "if they aren't owner submitted in OV by the time they
should be getting the drug test we can move them to terminated on our OBCL
extension for that week for 'Onboarding Not Completed'".
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.icd_onboarding import board as B, not_completed as NC


def _row(first, last, submit="", term="", done=0):
    r = {"Name": first, "Last Name": last, "Owner Submit": submit,
         B.TERMINATED_AT: term, B.REMOVED_WHY: "Quit" if term else ""}
    for i, c in enumerate(NC.CHART_STEPS):
        r[c] = "x" if i < done else ""
    return r


class WhatCountsAsSubmitted(unittest.TestCase):

    def test_the_words(self):
        for yes in ("Yes", "yes", "SUBMITTED", "done", "Complete", " y "):
            self.assertTrue(NC.is_submitted(yes), yes)

    def test_a_date_counts(self):
        """Some boards carry the day it was pressed. A date is the strongest
        possible yes -- refusing it would mark off exactly the people whose
        onboarding finished most cleanly."""
        for d in ("11/18", "2026-11-18", "11/18/2026", "11.18.26"):
            self.assertTrue(NC.is_submitted(d), d)

    def test_blank_and_no_do_not(self):
        for no in ("", "   ", "No", "-", "n/a", "pending"):
            self.assertFalse(NC.is_submitted(no), repr(no))


class WhoGetsMarked(unittest.TestCase):

    def test_an_unsubmitted_row_is_named(self):
        self.assertEqual(NC.unfinished([_row("Kip", "Wilson")])[0],
                         ["Kip Wilson"])

    def test_a_submitted_row_is_left_alone(self):
        self.assertEqual(NC.unfinished([_row("Ada", "Fournier", "Yes")])[0], [])

    def test_somebody_already_off_the_board_is_not_touched(self):
        """A second removal would overwrite a reason a PERSON may have
        chosen."""
        self.assertEqual(
            NC.unfinished([_row("Mia", "Reyes", "", term="2026-11-18")])[0], [])

    def test_a_row_with_no_name_is_skipped(self):
        self.assertEqual(NC.unfinished([_row("", "")])[0], [])


class TheRun(unittest.TestCase):

    def _run(self, rows, dry_run=True):
        said = []
        with mock.patch("automations.icd_onboarding.fillers.rows_anywhere",
                        return_value=rows), \
             mock.patch("automations.icd_onboarding.book.open_book"), \
             mock.patch("automations.icd_onboarding.sheet.terminate",
                        return_value=99) as term:
            n = NC.run("raf", today=dt.date(2026, 11, 25),
                       dry_run=dry_run, log=said.append)
        return n, " ".join(said), term

    def test_dry_by_default_and_writes_nothing(self):
        n, said, term = self._run([_row("Kip", "Wilson")])
        self.assertEqual(n, 1)
        term.assert_not_called()
        self.assertIn("would mark", said)

    def test_write_uses_the_one_machine_reason(self):
        n, said, term = self._run([_row("Kip", "Wilson")], dry_run=False)
        self.assertEqual(n, 99)
        self.assertEqual(term.call_args.kwargs["reason"],
                         B.NOT_COMPLETED_REASON)

    def test_it_marks_the_DRUG_TEST_week_not_this_one(self):
        """One place owns that arithmetic, so the mark and the send can never
        disagree about which cohort is three weeks old."""
        from automations.office_admin import wk3
        with mock.patch("automations.icd_onboarding.fillers.rows_anywhere",
                        return_value=[]) as rows:
            NC.run("raf", today=dt.date(2026, 11, 25), log=lambda *a: None)
        self.assertEqual(rows.call_args[0][1],
                         wk3.start_week_for(dt.date(2026, 11, 25)))

    def test_no_board_marks_nobody_and_says_so(self):
        """Saying "0 unfinished" about a week nobody looked at is the lie
        that makes somebody trust this later."""
        n, said, term = self._run([])
        self.assertEqual(n, 0)
        term.assert_not_called()
        self.assertIn("nothing read", said)


if __name__ == "__main__":
    unittest.main()


class FinishedTheChartIsNotUnfinished(unittest.TestCase):
    """On Raf's week of 11/16, 39 of 66 were never owner submitted -- but 33
    had done ZERO chart steps, which is what drifting away looks like, and
    three had done every one. Marking those three off would be the board
    calling somebody gone on the strength of a button nobody pressed."""

    def test_every_step_done_waits_on_the_press_instead(self):
        mark, waiting = NC.unfinished(
            [_row("Ada", "Fournier", done=len(NC.CHART_STEPS))])
        self.assertEqual(mark, [])
        self.assertEqual(waiting, ["Ada Fournier"])

    def test_zero_steps_done_is_marked(self):
        mark, waiting = NC.unfinished([_row("Kip", "Wilson", done=0)])
        self.assertEqual(mark, ["Kip Wilson"])
        self.assertEqual(waiting, [])

    def test_part_way_through_is_still_marked(self):
        mark, _ = NC.unfinished([_row("Mia", "Reyes", done=1)])
        self.assertEqual(mark, ["Mia Reyes"])

    def test_the_run_never_terminates_somebody_waiting_on_the_press(self):
        said = []
        with mock.patch("automations.icd_onboarding.fillers.rows_anywhere",
                        return_value=[_row("Ada", "F", done=len(NC.CHART_STEPS))]), \
             mock.patch("automations.icd_onboarding.sheet.terminate") as term:
            n = NC.run("raf", today=dt.date(2026, 11, 25), dry_run=False,
                       log=said.append)
        self.assertEqual(n, 0)
        term.assert_not_called()
        self.assertIn("press owed", " ".join(said))


class TheWeek3BoardKeepsGettingRefreshed(unittest.TestCase):
    """Megan, 2026-11-25: "if we had someone start this last monday and not
    be owner submitted until this coming tuesday, I could go to the OBCL ext
    for this week and they would show they did get ownersubmitted?"

    Until now, no. The hourly run only ever processed THIS week, so a tab
    stopped updating the moment its week ended -- and the week-3 check would
    have read a frozen column and marked somebody off whom the office had
    finished days before.
    """

    def test_from_ownerville_writes_this_week_and_the_week3_week(self):
        from automations.icd_onboarding import eco_steps as ES
        from automations.office_admin import wk3
        src = __import__("inspect").getsource(ES.from_ownerville)
        self.assertIn("start_week_for", src,
                      "the refresh must use the same arithmetic as the judge")
        self.assertIn("for wk in weeks", src)

    def test_the_two_weeks_are_this_one_and_three_back(self):
        from automations.office_admin import wk3
        today = dt.date(2026, 11, 25)
        self.assertEqual(wk3.start_week_for(today), dt.date(2026, 11, 8))
        # and the judge asks for exactly that week
        with mock.patch("automations.icd_onboarding.fillers.rows_anywhere",
                        return_value=[]) as rows:
            NC.run("raf", today=today, log=lambda *a: None)
        self.assertEqual(rows.call_args[0][1], wk3.start_week_for(today))
