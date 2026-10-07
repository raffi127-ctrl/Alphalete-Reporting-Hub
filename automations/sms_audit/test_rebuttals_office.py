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
