# -*- coding: utf-8 -*-
"""Per-office house rules: the Zoom link and the pay range.

Megan 2026-10-06: "the house rules will need to adapt per office".
Run: python -m unittest automations.sms_audit.test_rebuttals_office
"""
import unittest

from automations.sms_audit import rebuttals as RB


class Zoom(unittest.TestCase):
    def setUp(self):
        RB.OFFICE_ZOOM.clear()
        RB.set_zoom("11280", ["https://us02web.zoom.us/j/2935077152",
                              "2935077152"])

    def test_the_office_own_link_is_fine(self):
        self.assertIsNone(RB.wrong_zoom(
            "11280", "Zoom: https://us02web.zoom.us/j/2935077152"))

    def test_another_office_link_is_caught(self):
        self.assertTrue(RB.wrong_zoom(
            "11280", "Zoom: https://us05web.zoom.us/j/3106023771"))

    def test_a_wrong_meeting_id_is_caught(self):
        self.assertTrue(RB.wrong_zoom("11280", "Meeting ID: 310 602 3771"))

    def test_the_right_id_with_zoom_spacing_is_fine(self):
        self.assertIsNone(RB.wrong_zoom("11280", "Meeting ID: 293 507 7152"))

    def test_an_office_with_no_link_on_file_is_never_flagged(self):
        """A fact nobody supplied is a gap, not a fault."""
        self.assertIsNone(RB.wrong_zoom(
            "99999", "Zoom: https://us05web.zoom.us/j/3106023771"))

    def test_a_message_with_no_zoom_at_all_is_fine(self):
        self.assertIsNone(RB.wrong_zoom("11280", "See you at 9:15 tomorrow."))

    def test_clearing_the_links_turns_the_check_off(self):
        RB.set_zoom("11280", [])
        self.assertIsNone(RB.wrong_zoom(
            "11280", "Zoom: https://us05web.zoom.us/j/3106023771"))


class Pay(unittest.TestCase):
    def setUp(self):
        RB.OFFICE_PAY.clear()
        RB.set_pay("11280", 1000, 1500)

    def test_a_figure_inside_the_range_is_fine(self):
        self.assertIsNone(RB.pay_outside_range(
            "11280", "You'd earn $1,200 a week plus commission."))

    def test_a_figure_under_the_floor_is_caught(self):
        self.assertTrue(RB.pay_outside_range(
            "11280", "It's about $600 per week to start."))

    def test_a_figure_over_the_ceiling_is_caught(self):
        self.assertTrue(RB.pay_outside_range(
            "11280", "Reps make $4,000 a week here."))

    def test_a_range_inside_the_range_is_fine(self):
        self.assertIsNone(RB.pay_outside_range(
            "11280", "Weekly pay is $1,000 - $1,500."))

    def test_an_office_with_no_range_on_file_is_never_flagged(self):
        self.assertIsNone(RB.pay_outside_range(
            "99999", "It's about $600 per week."))

    def test_a_price_that_is_not_weekly_pay_is_ignored(self):
        self.assertIsNone(RB.pay_outside_range(
            "11280", "The plan is $60 a month."))

    def test_the_word_base_is_still_global(self):
        """Ruling 1 applies to every office, range or no range."""
        self.assertTrue(RB.says_base_pay("There is a base pay of $1,200."))


if __name__ == "__main__":
    unittest.main()


class StreetBoundary(unittest.TestCase):
    """A street suffix has to be a word, not the end of one.

    Megan 2026-10-06, shown a Zoom confirmation flagged as a wrong
    address: "last one isn't an address". "Rd" was matching the "rd" in
    "forward", so a meeting id plus a sentence read as a street."""

    def setUp(self):
        RB.ADDRESS_HISTORY.clear()
        RB.set_address_history(
            "11280", "5217 Tennyson Pkwy, Suite 100, Plano, Texas 75024",
            "3100 Premier Drive, Suite 207, Irving, Texas 75063")

    def test_a_meeting_id_is_not_an_address(self):
        self.assertIsNone(RB.wrong_address(
            "11280", "Meeting ID: 293 507 7152 We look forward to "
                     "speaking with you!"))

    def test_forward_does_not_become_a_road(self):
        self.assertIsNone(RB.wrong_address(
            "11280", "I look forward to it, 1234 is my code"))

    def test_a_genuinely_wrong_address_still_fires(self):
        self.assertTrue(RB.wrong_address(
            "11280", "Our office is at 3100 Premier Drive, Suite 232 "
                     "Irving, TX 75063"))

    def test_the_old_street_after_the_move_still_fires(self):
        self.assertTrue(RB.wrong_address(
            "11280", "Come to 3100 Premier Dr, Irving TX"))

    def test_the_current_address_is_clean(self):
        self.assertIsNone(RB.wrong_address(
            "11280", "We are at 5217 Tennyson Pkwy Suite 100 Plano, TX"))

    def test_a_street_named_in_full_is_not_split(self):
        self.assertTrue(RB.wrong_address(
            "11280", "We're at 1901 N Highway 360, Grand Prairie"))


class UnitBoundary(unittest.TestCase):
    """A suite keyword has to be a word of its own.

    Megan 2026-10-06, shown September texts carrying the September
    address: "this address was correct on this week". "Ste" was matching
    inside "yesterday" and capturing "rday" as the suite number, so a
    correct address failed the suite check."""

    SEP = __import__("datetime").date(2026, 9, 22)
    OCT = __import__("datetime").date(2026, 10, 3)

    def setUp(self):
        RB.ADDRESS_HISTORY.clear()
        RB.set_address_history(
            "11280", "5217 Tennyson Pkwy, Suite 100, Plano, Texas 75024",
            "3100 Premier Drive, Suite 207, Irving, Texas 75063",
            self.OCT.replace(day=2))

    YESTERDAY = ("The text and email I sent yesterday has 3100 Premier "
                 "Drive Suite 207 Irving, Texas 75063")

    def test_yesterday_is_not_a_suite(self):
        self.assertIsNone(RB.wrong_address("11280", self.YESTERDAY, self.SEP))

    def test_the_same_text_after_the_move_is_wrong(self):
        self.assertTrue(RB.wrong_address("11280", self.YESTERDAY, self.OCT))

    def test_the_right_address_in_its_own_week_is_clean(self):
        self.assertIsNone(RB.wrong_address(
            "11280", "Our office is at 3100 Premier Drive, Suite 207, "
                     "Irving, TX", self.SEP))

    def test_a_genuinely_wrong_suite_still_fires_in_that_week(self):
        self.assertTrue(RB.wrong_address(
            "11280", "Our office is at 3100 Premier Drive, Suite 232 "
                     "Irving, TX", self.SEP))
