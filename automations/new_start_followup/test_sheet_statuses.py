"""The statuses come off the OBCL sheet, not the screenshot (Megan 2026-09-26).

Aisha's post stays the gate — nothing reads the sheet before it — but once it is
up, the sheet is what says who is starting. These pin the three things that
were wrong before: Final Status was invisible, the drop rules disagreed between
this report and Blue Ink, and each status was tested against every rule.
"""
import datetime as dt
import unittest
from unittest import mock

from automations.new_start_followup import obcl, screenshot_roster as SR
from automations.shared import new_start_eligibility as E

MONDAY = dt.date(2026, 9, 28)


def _start(name, status="", bg="", friday="", interviewer="Lead One", row=3):
    first, _, last = name.partition(" ")
    return obcl.NewStart(interviewer=interviewer, name=f"{first} {last}".strip(),
                         phone="", status=status, row=row,
                         confirmation=friday, bg_status=bg)


def _row(name, interviewer="Lead One", friday="", bg=""):
    first, _, last = name.partition(" ")
    return {"interviewer": interviewer, "name": first, "last_name": last,
            "confirmation": friday, "bg_status": bg}


class OneRuleForTheFamily(unittest.TestCase):
    def test_blueink_and_the_followup_agree(self):
        """The whole point: one tab cannot give two answers."""
        from automations.blueink_docs import config as C
        self.assertIs(C.FINAL_STATUS_BLOCK_MARKERS, E.FINAL_STATUS_BLOCK_MARKERS)
        self.assertIs(C.BG_STATUS_BLOCK, E.BG_STATUS_BLOCK)
        self.assertIs(C.FRIDAY_BLOCK, E.FRIDAY_BLOCK)

    def test_the_statuses_that_used_to_slip_through(self):
        """Terminated / Quit / Backed Out / Adverse Action were skipped for
        documents but their interviewer was still counted as owing a text."""
        for status in ("Terminated", "Quit before Classroom", "Backed Out",
                       "Quit during Classroom"):
            self.assertTrue(_start("A B", status=status).dropped, status)
        self.assertTrue(_start("A B", bg="Adverse Action").dropped)

    def test_progress_values_still_count(self):
        for status in ("Showed Up To CR", "Owner submitted", "Started",
                       "Activations Email Sent", "Needs BlueInk", ""):
            self.assertFalse(_start("A B", status=status).dropped, status)

    def test_a_column_is_only_tested_against_its_own_rule(self):
        """'Declined' blocks in Friday Confirmation. 'Passed' in BG Status must
        never be read against the Friday list, and vice versa."""
        self.assertTrue(_start("A B", friday="Declined").dropped)
        self.assertFalse(_start("A B", bg="Passed", friday="Confirmed: OTP").dropped)
        self.assertFalse(_start("A B", bg="Taken - Pending",
                                friday="NA: Sent Text").dropped)

    def test_reason_names_its_column(self):
        self.assertEqual(_start("A B", status="Terminated").drop_reason,
                         "Final Status: Terminated")
        self.assertEqual(_start("A B", bg="Failed").drop_reason,
                         "BG Status: Failed")


class EnrichFromSheet(unittest.TestCase):
    def _enrich(self, rows, starts, tab="D2D OBCL 9.28"):
        with mock.patch.object(obcl, "read_new_starts",
                               return_value=(MONDAY, tab, starts)):
            return SR.enrich_from_sheet(rows, MONDAY)

    def test_the_sheet_overwrites_what_the_picture_said(self):
        """The screenshot was taken before the status changed."""
        rows = [_row("Ana Diaz", friday="Confirmed: OTP")]
        self._enrich(rows, [_start("Ana Diaz", status="Quit before Classroom")])
        self.assertEqual(rows[0]["final_status"], "Quit before Classroom")
        self.assertTrue(SR.is_dropped(rows[0]))

    def test_a_sheet_that_clears_a_status_un_drops_them(self):
        rows = [_row("Ana Diaz", friday="Declined")]
        self._enrich(rows, [_start("Ana Diaz", friday="Confirmed: Via Sms")])
        self.assertFalse(SR.is_dropped(rows[0]))

    def test_a_name_the_sheet_does_not_have_keeps_its_own_statuses(self):
        """A failed match must never silently delete a new start."""
        rows = [_row("Ana Diaz", friday="Declined"), _row("Ben Cole")]
        notes = self._enrich(rows, [_start("Ben Cole")])
        self.assertTrue(SR.is_dropped(rows[0]))   # kept the screenshot's word
        self.assertFalse(SR.is_dropped(rows[1]))
        self.assertTrue(any("not on" in n and "Ana" in n for n in notes))

    def test_an_unreadable_sheet_is_advisory_not_fatal(self):
        rows = [_row("Ana Diaz", friday="Declined")]
        with mock.patch.object(obcl, "read_new_starts",
                               side_effect=RuntimeError("no tab")):
            notes = SR.enrich_from_sheet(rows, MONDAY)
        self.assertTrue(any("WARNING" in n for n in notes))
        self.assertTrue(SR.is_dropped(rows[0]))   # the roll call still stands

    def test_duplicate_rows_that_disagree_do_not_drop_anyone(self):
        rows = [_row("Ana Diaz")]
        notes = self._enrich(rows, [_start("Ana Diaz", status="Quit"),
                                    _start("Ana Diaz", status="", row=40)])
        self.assertFalse(SR.is_dropped(rows[0]))
        self.assertTrue(any("disagree" in n for n in notes))

    def test_duplicate_rows_that_agree_still_drop(self):
        rows = [_row("Ana Diaz")]
        self._enrich(rows, [_start("Ana Diaz", status="Terminated"),
                            _start("Ana Diaz", status="Terminated", row=40)])
        self.assertTrue(SR.is_dropped(rows[0]))

    def test_accented_names_match(self):
        rows = [_row("Anh Đinh")]
        self._enrich(rows, [_start("Anh Dinh", status="Terminated")])
        self.assertTrue(SR.is_dropped(rows[0]))


class TheGateStillComesFirst(unittest.TestCase):
    def test_no_week_means_no_sheet_read(self):
        """Picking 'the newest tab' without a week is how last week's statuses
        get stamped onto this week."""
        rows = [_row("Ana Diaz")]
        with mock.patch.object(SR, "enrich_from_sheet") as spy:
            SR._with_sheet_statuses(rows, None, True)
        spy.assert_not_called()

    def test_owed_counts_names_the_blocking_column(self):
        rows = [_row("Ana Diaz"), _row("Ben Cole")]
        rows[0]["final_status"] = "Quit before Classroom"
        owed, dropped = SR.owed_counts(rows)
        self.assertEqual(owed, {"Lead One": 1})
        self.assertIn("Final Status: Quit before Classroom", dropped[0])


if __name__ == "__main__":
    unittest.main()


class ChartDivergenceIsReported(unittest.TestCase):
    """Two readers of one tab disagree about where it ends. Neither rule is
    wrong; the two silently differing IS. See obcl.warn_if_charts_disagree.
    """

    HEAD = ["#", "2ND Round Interviewer", "Name", "Last Name", "Email"]

    def _grid(self, extra_rows):
        return ([["9/28/2026", "", "", "", ""], self.HEAD,
                 ["1", "Lead One", "Ana", "Diaz", "ana@x.com"],
                 ["2", "Lead Two", "Ben", "Cole", "ben@x.com"]] + extra_rows)

    def _starts(self, grid):
        """What obcl's own walk sees: stop at the first blank after the header."""
        out = []
        for n, row in enumerate(grid[2:], start=3):
            if not (row[1].strip() or row[2].strip()):
                break
            out.append(obcl.NewStart(interviewer=row[1], name=row[2], phone="",
                                     status="", row=n))
        return out

    def test_no_warning_when_the_tab_has_one_clean_chart(self):
        grid = self._grid([])
        notes = obcl.warn_if_charts_disagree(grid, self._starts(grid), "T")
        self.assertEqual(notes, [])

    def test_warns_about_people_below_the_blank_this_walk_stopped_at(self):
        """A second chart after a gap: Blue Ink and Digi Docs would include
        Cal, this report would not."""
        grid = self._grid([["", "", "", "", ""],
                           ["3", "Lead Three", "Cal", "Reed", "cal@x.com"]])
        starts = self._starts(grid)
        self.assertEqual(len(starts), 2)              # it stopped at the blank
        notes = obcl.warn_if_charts_disagree(grid, starts, "D2D OBCL 9.28")
        self.assertTrue(notes, "the divergence was not reported")
        self.assertIn("WARNING", notes[0])
        self.assertIn("D2D OBCL 9.28", notes[0])
        self.assertTrue(any("Cal" in n for n in notes))

    def test_a_broken_chart_parser_never_breaks_the_read(self):
        """The check is a diagnostic. It must not be able to fail the report."""
        from automations.shared import obcl_charts as oc
        with mock.patch.object(oc, "find_charts",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(
                obcl.warn_if_charts_disagree(self._grid([]), [], "T"), [])
