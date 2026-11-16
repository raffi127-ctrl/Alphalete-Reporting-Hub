"""The board-sourced roster: who gets documents when the source is OUR board.

The thing most worth pinning is the gate. On Raf's tab "not starting" is words
in a Final Status cell; on the board it is a date in `Terminated`. Two of the
five removal reasons the panel offers do not match any block marker in
`shared.new_start_eligibility`, so a reason-text gate would mail documents to
people who had been clicked off.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.blueink_docs import board_roster as BR
from automations.icd_onboarding import board as B
from automations.shared import new_start_eligibility as E

MON = dt.date(2026, 11, 16)
WEEK = B.week_label(MON)


def row(**kw):
    r = {"Week of": WEEK, "Name": "Ada", "Last Name": "Byron",
         "Email": "ada@example.com", "Phone": "817-395-7537"}
    r.update(kw)
    return r


class TheGateIsTheDateNotTheWords(unittest.TestCase):

    def test_every_removal_reason_the_panel_offers_blocks_the_send(self):
        """The whole reason this gates on the date.

        "Left Classroom" and "Did not show to day 1 Classroom" match NO marker
        in the family-wide rule, so a text gate would let both through.
        """
        for why in B.REMOVAL_REASONS:
            with self.subTest(reason=why):
                p = BR._one(row(**{B.TERMINATED_AT: "11/16/2026",
                                   B.REMOVED_WHY: why}), MON)
                self.assertFalse(p.eligible, "%r was not blocked" % why)
                self.assertIn(why, p.skip_reason)

    def test_the_reason_text_alone_would_not_have_blocked_two_of_them(self):
        """Proof the danger is real, not theoretical. If this ever fails it is
        because the shared markers grew and the comment should be revisited."""
        slipped = [w for w in B.REMOVAL_REASONS if not E.not_starting(w, "", "")]
        self.assertEqual(sorted(slipped),
                         ["Did not show to day 1 Classroom", "Left Classroom"])

    def test_a_removal_with_no_reason_recorded_still_blocks(self):
        """Every removal before the Removed Because fix has a blank reason."""
        p = BR._one(row(**{B.TERMINATED_AT: "11/16/2026"}), MON)
        self.assertFalse(p.eligible)
        self.assertIn("taken off the board", p.skip_reason)

    def test_a_reason_without_a_date_is_not_a_removal(self):
        """Somebody typing in the reason column has not removed anybody."""
        p = BR._one(row(**{B.REMOVED_WHY: "Terminated"}), MON)
        self.assertTrue(p.eligible, p.skip_reason)


class WhoStillGetsDocuments(unittest.TestCase):

    def test_a_plain_row_is_eligible(self):
        self.assertTrue(BR._one(row(), MON).eligible)

    def test_docs_go_out_while_the_background_check_is_still_moving(self):
        for bg in ("", "Sent", "Taken - Pending", "Review", "Complete", "Passed"):
            with self.subTest(bg=bg):
                self.assertTrue(BR._one(row(**{"BG Status": bg}), MON).eligible,
                                "%r should still get documents" % bg)

    def test_a_failed_check_stops_the_send(self):
        for bg in ("Failed", "Adverse Action"):
            with self.subTest(bg=bg):
                p = BR._one(row(**{"BG Status": bg}), MON)
                self.assertFalse(p.eligible)
                self.assertIn("BG Status", p.skip_reason)

    def test_not_showing_up_is_never_a_gate(self):
        """Documents go out BEFORE the first day; at send time nobody has shown
        up, and somebody missing Monday may walk in Tuesday."""
        p = BR._one(row(**{B.SHOWED_UP: ""}), MON)
        self.assertTrue(p.eligible, p.skip_reason)

    def test_no_email_is_a_skip_with_its_own_words(self):
        p = BR._one(row(**{"Email": ""}), MON)
        self.assertFalse(p.eligible)
        self.assertIn("no email", p.skip_reason)

    def test_a_malformed_email_is_a_skip(self):
        p = BR._one(row(**{"Email": "ada at example"}), MON)
        self.assertFalse(p.eligible)
        self.assertIn("valid", p.skip_reason)

    def test_a_row_with_no_name_at_all_is_not_a_person(self):
        self.assertIsNone(BR._one(row(**{"Name": "", "Last Name": ""}), MON))


class NothingFromThisRosterCanTintACell(unittest.TestCase):
    """The tab reader hands back a row so the sender can tint Raf's column D.
    There is no such column here, and the board's own Blue Ink column belongs
    to the onboarding run."""

    def test_no_row_number_and_no_blueink_column(self):
        p = BR._one(row(), MON)
        self.assertEqual(p.row, 0)
        self.assertEqual(p.blueink_col, 0)
        self.assertEqual(p.first_col, 0)

    def test_the_tab_it_names_is_the_onboarding_board(self):
        self.assertEqual(BR._one(row(), MON).tab, B.TAB)


class ItKeepsTheShapeTheSenderExpects(unittest.TestCase):

    def test_a_board_person_is_a_newstart(self):
        from automations.blueink_docs.roster import NewStart
        self.assertIsInstance(BR._one(row(), MON), NewStart)

    def test_name_and_key_still_work(self):
        p = BR._one(row(), MON)
        self.assertEqual(p.name, "Ada Byron")
        self.assertEqual(p.key, "byron|ada")

    def test_final_status_is_blank_rather_than_invented(self):
        """This board has no such column, and a made-up value would be read as
        a real outcome by anything that logs it."""
        p = BR._one(row(), MON)
        self.assertEqual(p.final_status, "")
        self.assertEqual(p.friday, "")


class FromBoardReadsThroughTheRoutedReader(unittest.TestCase):

    def test_it_returns_blocked_people_too_so_a_dry_run_can_say_why(self):
        from automations.icd_onboarding import fillers as F
        was = F.rows_anywhere
        F.rows_anywhere = lambda o, w, **k: [
            row(), row(**{"Name": "Grace", "Email": ""}),
            row(**{"Name": "Alan", B.TERMINATED_AT: "11/16/2026"}),
        ]
        try:
            got = BR.from_board("raf", MON, log=lambda *_: None)
        finally:
            F.rows_anywhere = was
        self.assertEqual(len(got), 3)
        self.assertEqual([p.first for p in got if p.eligible], ["Ada"])

    def test_an_empty_week_is_an_empty_list_not_an_error(self):
        from automations.icd_onboarding import fillers as F
        was = F.rows_anywhere
        F.rows_anywhere = lambda o, w, **k: []
        try:
            self.assertEqual(BR.from_board("raf", MON, log=lambda *_: None), [])
        finally:
            F.rows_anywhere = was

    def test_already_sent_reads_the_boards_own_tick(self):
        people = [BR._one(row(), MON),
                  BR._one(row(**{"Name": "Grace", "Blue Ink": "11/14/2026"}), MON)]
        self.assertEqual([p.first for p in BR.already_sent(people)], ["Grace"])


if __name__ == "__main__":
    unittest.main()


class MarkedNoShowInApplicantStreamStopsTheSend(unittest.TestCase):
    """Megan, 2026-11-16, asked what should stop a send off this board:
    "1 would be if they are marked no show in app stream"."""

    def test_an_explicit_no_show_is_not_starting(self):
        p = BR._one(row(**{B.SHOWED_UP: B.NO_SHOW}), MON)
        self.assertFalse(p.eligible)
        self.assertIn("no show in ApplicantStream", p.skip_reason)

    def test_a_blank_showed_up_is_not_a_no_show(self):
        """Nobody has said yet. Somebody missing Monday may walk in Tuesday,
        and the board has never marked anyone off for a blank."""
        for blank in ("", "   ", None):
            with self.subTest(value=blank):
                self.assertTrue(BR._one(row(**{B.SHOWED_UP: blank}), MON).eligible)

    def test_a_date_means_they_turned_up_and_never_blocks(self):
        p = BR._one(row(**{B.SHOWED_UP: "11/16/2026"}), MON)
        self.assertTrue(p.eligible, p.skip_reason)

    def test_the_words_are_matched_however_they_are_cased(self):
        for said in ("No Show", "no show", "NO SHOW", " No Show "):
            with self.subTest(value=said):
                self.assertFalse(BR._one(row(**{B.SHOWED_UP: said}), MON).eligible)

    def test_a_removal_still_wins_over_the_showed_up_column(self):
        """Somebody clicked off AND marked present is still off."""
        p = BR._one(row(**{B.SHOWED_UP: "11/16/2026",
                           B.TERMINATED_AT: "11/16/2026",
                           B.REMOVED_WHY: "Terminated"}), MON)
        self.assertFalse(p.eligible)
        self.assertIn("Taken off the board", p.skip_reason)


class ShowedUpAdvancesRatherThanTicking(unittest.TestCase):
    """blank -> No Show -> a date, and never backwards. The Tuesday walk-in is
    the case this exists for."""

    def test_a_date_outranks_no_show(self):
        self.assertGreater(B.status_rank("11/16/2026", B.SHOWED_UP),
                           B.status_rank(B.NO_SHOW, B.SHOWED_UP))

    def test_no_show_outranks_nobody_having_said(self):
        self.assertGreater(B.status_rank(B.NO_SHOW, B.SHOWED_UP),
                           B.status_rank("", B.SHOWED_UP))

    def test_it_is_a_status_column_not_a_tick(self):
        self.assertIn(B.SHOWED_UP, B.STATUS_STEPS)

    def test_the_background_check_ranking_is_untouched(self):
        """Showed Up has its own scale; asking for it by column is what keeps
        a date from scoring 0 against the background-check words."""
        self.assertEqual(B.status_rank("11/16/2026"), 0)
        self.assertEqual(B.status_rank("Passed"), 5)
        self.assertGreater(B.status_rank("Passed"), B.status_rank("Sent"))
