"""A zero in the tab's date is the same week (Eve 2026-11-01)."""
import datetime as dt
import unittest
from types import SimpleNamespace as NS

from automations.alphalete_sales_board import fill, lanes, tab_names as TN
from automations.new_starts_box import sources


class TabNames(unittest.TestCase):
    def test_zero_is_the_same_week(self):
        self.assertEqual(TN.find(["Sales Board WE 11.01"], "Sales Board WE 11.1"),
                         "Sales Board WE 11.01")
        self.assertEqual(TN.find(["Line Up WE 11.01"], "Line Up WE 11.1"),
                         "Line Up WE 11.01")
        self.assertEqual(TN.find(["Line Up WE 1.05"], "Line Up WE 1.5"), "Line Up WE 1.05")

    def test_other_days_and_tabs_do_not_match(self):
        for other in ("Sales Board WE 11.10", "Sales Board WE 1.1", "Line Up WE 11.1",
                      "SANDBOX — Sales Board WE 11.1", "Sales Board WE 11.1 Eve Edits"):
            self.assertIsNone(TN.find([other], "Sales Board WE 11.1"), other)

    def test_exact_name_wins(self):
        self.assertEqual(TN.find(["Sales Board WE 11.01", "Sales Board WE 11.1"],
                                 "Sales Board WE 11.1"), "Sales Board WE 11.1")

    def test_the_sweep_and_the_lanes_open_it(self):
        ws = NS(title="Sales Board WE 11.01")
        gc = NS(open_by_key=lambda _id: NS(worksheets=lambda: [ws]))
        self.assertIs(fill.open_tab(dt.date(2026, 11, 1), gc), ws)
        self.assertIs(lanes._find_ws([ws], "Sales Board WE 11.1"), ws)

    def test_new_starts_box_opens_the_line_up(self):
        ws = NS(title="Line Up WE 11.01")
        book = NS(title="b", worksheets=lambda: [ws])
        self.assertIs(sources.open_tab(book, "Line Up WE 11.1", "line up"), ws)


if __name__ == "__main__":
    unittest.main()
