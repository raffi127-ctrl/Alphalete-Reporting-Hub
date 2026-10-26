"""Pure rules of the Monday roll (week_roll.py). Run:
python -m unittest automations.alphalete_sales_board.test_week_roll"""
import datetime as dt
import unittest

from automations.alphalete_sales_board import week_roll as W

SPELLED = {2: "2nd Wk", 3: "3rd Wk", 4: "4th Wk", 5: "5th wk+"}


class StatusAndName(unittest.TestCase):
    def test_status_moves_one_week_in_the_boards_spelling(self):
        self.assertEqual(W.next_status("1st Wk", SPELLED), (1, "2nd Wk"))
        self.assertEqual(W.next_status("3rd Wk", SPELLED), (3, "4th Wk"))
        self.assertEqual(W.next_status("4th Wk", SPELLED), (4, "5th wk+"))

    def test_last_bucket_and_others_stay(self):
        for s in ("5th wk+", "RT", "Extra", ""):
            self.assertIsNone(W.next_status(s, SPELLED))

    def test_only_weeks_2_and_3_carry_the_tag(self):
        self.assertEqual(W.next_name("Tony Jones", 1), "Tony Jones (Wk 2)")
        self.assertEqual(W.next_name("Ana (Wk 2)", 2), "Ana (Wk 3)")
        self.assertEqual(W.next_name("Kayla Sprague (Wk 3)", 3), "Kayla Sprague")
        self.assertEqual(W.next_name("Grayson Holly", 4), "Grayson Holly")

    def test_base_name(self):
        self.assertEqual(W.base_name("Gabriel  (Gabe) Caldwell (Wk 2)"), "Gabriel  (Gabe) Caldwell")
        self.assertEqual(W.base_name("Bill Hirwa (NC)"), "Bill Hirwa (NC)")


class Tabs(unittest.TestCase):
    def test_names_and_padded_day(self):
        sun = dt.date(2026, 11, 1)
        self.assertEqual(W.tab_title(W.BOARD_PREFIX, sun), "Sales Board WE 11.1")
        titles = ["Sales Board WE 11.1", "Line Up WE 11.01", "Line Up WE 10.25"]
        self.assertEqual(W.find_tab(titles, W.LINEUP_PREFIX, sun), "Line Up WE 11.01")
        self.assertIsNone(W.find_tab(["SANDBOX — Sales Board WE 11.1"], W.BOARD_PREFIX, sun))

    def test_week_label(self):
        self.assertEqual(W.week_label(dt.date(2026, 10, 26)), "WE 10/26 - 11/1")


if __name__ == "__main__":
    unittest.main()
