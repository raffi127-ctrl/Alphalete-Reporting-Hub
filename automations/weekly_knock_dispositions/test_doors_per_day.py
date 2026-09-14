"""Mon–Fri Avg Doors / Day divides by the days a rep actually knocked, offline.

Raf 2026-09-14, on his 9/12 captainship email: "my average knocks per day seem
low for Monday through Friday … every day before it showed over 100". The
weekly divided every rep's doors by 5, so a missed day counted as a day of 0
doors and the summary read 82.61 under five dailies that all read over 100.

    python -m unittest automations.weekly_knock_dispositions.test_doors_per_day
"""
from __future__ import annotations

import unittest

from automations.total_knocks.pull import COL_REP
from automations.weekly_knock_dispositions import board as B
from automations.weekly_knock_dispositions.pull import (
    K_DAILY_KNOCKS, K_TALK_TO, K_TOTAL_KNOCKS)


def _rep(name, daily):
    return {COL_REP: name, K_TALK_TO: 10, K_TOTAL_KNOCKS: sum(daily),
            K_DAILY_KNOCKS: list(daily)}


TWO_DAYS = _rep("Two Days", [120, 100, 0, 0, 0, 50])
FULL_WEEK = _rep("Full Week", [100, 100, 100, 100, 100, 0])
WALK_ON = _rep("Walk On", [15, 0, 0, 0, 0, 0])
DOORS = B.HEADERS.index(B.COL_DOORS_PER_DAY)


class RepCell(unittest.TestCase):
    def test_divides_by_the_weekdays_knocked_not_by_five(self):
        # 220 doors over the 2 days worked — not 220 / 5 = 44.
        self.assertEqual(B._doors_per_day(TWO_DAYS), "110")

    def test_saturday_stays_out(self):
        self.assertEqual(B._knocked_weekdays(TWO_DAYS), 2)

    def test_a_day_counts_only_over_20_doors(self):
        rec = _rep("Edge", [20, 21, 0, 0, 0, 0])
        self.assertEqual(B._knocked_weekdays(rec), 1)
        self.assertEqual(B._doors_per_day(rec), "41")

    def test_no_weekday_over_20_is_blank_not_zero(self):
        self.assertEqual(B._doors_per_day(WALK_ON), "")
        self.assertFalse(B.is_knocking(WALK_ON))

    def test_no_per_day_counts_is_blank(self):
        self.assertEqual(B._doors_per_day({COL_REP: "Old", K_TOTAL_KNOCKS: 9}),
                         "")


class SummaryRow(unittest.TestCase):
    def test_office_doors_over_rep_days_knocked(self):
        row = B.totals_row([TWO_DAYS, FULL_WEEK, WALK_ON], None, [])
        # (220 + 500 + 15) doors over (2 + 5 + 0) rep-days = 105; the old
        # 735 / 5 / 3 = 49 is what made the weekly read low.
        self.assertEqual(row[DOORS], "105")

    def test_rep_count_matches_the_doors_cells(self):
        row = B.totals_row([TWO_DAYS, FULL_WEEK, WALK_ON], None, [])
        self.assertEqual(row[0], "2 of 3")

    def test_the_rep_rows_draw_the_same_cells(self):
        rows = B.compute_rows([TWO_DAYS, FULL_WEEK, WALK_ON], None)
        by_name = {r[1]: r[DOORS] for r in rows[1:]}
        self.assertEqual(by_name, {"Full Week": "100", "Two Days": "110",
                                   "Walk On": ""})


if __name__ == "__main__":
    unittest.main()
