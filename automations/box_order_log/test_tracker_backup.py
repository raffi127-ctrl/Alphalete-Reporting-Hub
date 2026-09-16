"""The Rep Lvl tracker back-up: parse, merge, and the Vantura fallback.

    python -m unittest automations.box_order_log.test_tracker_backup -v
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.box_order_log import tracker_backup as tb

TODAY = dt.date(2026, 9, 16)

# The shape of the 2026-09-16 view: WE 9/20, only Monday in it yet.
EXPORT = [
    ["Rep Name", "Owner Name", "Mon (09-14)", "Grand Total"],
    ["Grand Total", "", "40", "40"],
    ["Joelle Vivian Barajas", "Carlos Hidalgo", "3", "3"],
    ["Emily Garcia", "Roshan Ahmad", "3", "3"],
    ["Cinthya reyes", "Carlos Hidalgo", "2", "2"],
    ["Kandice Michelle Flores", "Carlos Hidalgo", "0", "0"],
    ["Tara Lynn Ecklof", "Carlos Hidalgo", "", ""],
]


class ParseTest(unittest.TestCase):
    def test_carlos_rows_by_day_only(self):
        counts, days = tb.parse(EXPORT, TODAY)
        self.assertEqual(days, [dt.date(2026, 9, 14)])
        self.assertEqual(counts, {
            ("Joelle Vivian Barajas", dt.date(2026, 9, 14)): 3,
            ("Cinthya reyes", dt.date(2026, 9, 14)): 2,
            ("Kandice Michelle Flores", dt.date(2026, 9, 14)): 0})

    def test_spanish_headers_and_a_second_header_row(self):
        rows = [["", "", "Sale Date", ""],
                ["Rep Name", "Owner Name", "lun (09-07)", "mar (09-08)"],
                ["Gary Van Whitaker", "Carlos Hidalgo", "1", ""]]
        counts, days = tb.parse(rows, TODAY)
        self.assertEqual(days, [dt.date(2026, 9, 7), dt.date(2026, 9, 8)])
        self.assertEqual(counts, {("Gary Van Whitaker",
                                   dt.date(2026, 9, 7)): 1})

    def test_weekday_must_agree_and_no_future_days(self):
        self.assertIsNone(tb.day_of("Tue (09-14)", TODAY))
        self.assertEqual(tb.day_of("Wed (12-31)", dt.date(2026, 1, 2)),
                         dt.date(2025, 12, 31))

    def test_no_day_columns_is_nothing(self):
        self.assertEqual(tb.parse([["Rep Name", "Owner Name"]], TODAY),
                         ({}, []))


class WeekForTest(unittest.TestCase):
    def test_box_weeks_close_on_sunday(self):
        self.assertEqual(tb.week_for(dt.date(2026, 9, 15)),
                         dt.date(2026, 9, 20))
        # Monday's "yesterday" is Sunday: last week, not this one.
        self.assertEqual(tb.week_for(dt.date(2026, 9, 13)),
                         dt.date(2026, 9, 13))


class MergeTest(unittest.TestCase):
    def test_covered_days_replaced_older_kept_and_marked(self):
        old = [tb.HEADER, ["Gary Van Whitaker", "9/12/2026", "2"],
               ["Joelle Vivian Barajas", "9/14/2026", "9"]]
        counts, days = tb.parse(EXPORT, TODAY)
        body = tb.merge(old, counts, days)
        self.assertEqual(body, [
            tb.HEADER,
            ["Gary Van Whitaker", "9/12/2026", "2"],
            [tb.COVERED, "9/14/2026", "0"],
            ["Cinthya reyes", "9/14/2026", "2"],
            ["Joelle Vivian Barajas", "9/14/2026", "3"]])
        self.assertTrue(tb.covers(body, dt.date(2026, 9, 14)))
        self.assertFalse(tb.covers(body, dt.date(2026, 9, 12)))
        self.assertFalse(tb.covers(body, dt.date(2026, 9, 15)))
        self.assertEqual(tb.counts_for(body, dt.date(2026, 9, 14)),
                         {"Cinthya reyes": 2, "Joelle Vivian Barajas": 3})


class VanturaFallbackTest(unittest.TestCase):
    def test_tracker_names_reach_the_board_rows(self):
        from automations.vantura_orderlog_sales import run

        class Sh:
            def worksheet(self, _title):
                class Ws:
                    def get_all_values(self):
                        return tb.merge([], *tb.parse(EXPORT, TODAY))
                return Ws()

        counts = run.counts_box_tracker(Sh(), dt.date(2026, 9, 14))
        rows = {"joelle barajas": 9, "cinthya reyes": 10}
        self.assertEqual(run.match_rep("joelle vivian barajas", rows),
                         "joelle barajas")
        self.assertEqual(dict(counts), {"joelle vivian barajas": 3,
                                        "cinthya reyes": 2})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
