"""Mon–Fri Avg Knocks / Hr on the weekly board, offline.

Raf 2026-09-15: "for the weekly disposition NDS and Fiber are missing 'daily
knocks per hour'". The cell is the MEAN of the rep's own daily rates (that
day's doors over that day's first→last span), over the weekdays they cleared
the doors bar — the same days Mon–Fri Avg Doors / Day divides by.

    python -m unittest automations.weekly_knock_dispositions.test_knocks_per_hour
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.total_knocks.pull import COL_REP
from automations.weekly_knock_dispositions import board as B
from automations.weekly_knock_dispositions import pull as P
from automations.weekly_knock_dispositions.pull import (
    K_DAILY_KNOCKS, K_DAILY_SPAN_MIN, K_TALK_TO, K_TOTAL_KNOCKS)


def _rep(name, daily, spans=None):
    rec = {COL_REP: name, K_TALK_TO: 10, K_TOTAL_KNOCKS: sum(daily),
           K_DAILY_KNOCKS: list(daily)}
    if spans is not None:
        rec[K_DAILY_SPAN_MIN] = list(spans)
    return rec


# Mon 120 doors over 4h = 30/hr, Tue 100 over 5h = 20/hr → 25. Saturday's 50
# over 2h stays out, and so does the walk-on day.
TWO_DAYS = _rep("Two Days", [120, 100, 15, 0, 0, 50],
                [240, 300, 60, 0, 0, 120])
STEADY = _rep("Steady", [90, 90, 90, 90, 90, 0],
              [180, 180, 180, 180, 180, 0])            # 30/hr every day
OLD_CACHE = _rep("Old Cache", [100, 100, 100, 100, 100, 0])   # no spans
KPH = B.HEADERS.index(B.COL_KNOCKS_PER_HR)


class RepCell(unittest.TestCase):
    def test_mean_of_the_days_own_rates(self):
        self.assertAlmostEqual(B._knocks_per_hr(TWO_DAYS), 25.0)

    def test_saturday_and_walk_on_days_stay_out(self):
        rec = _rep("Sat Only", [0, 0, 0, 0, 0, 200], [0, 0, 0, 0, 0, 240])
        self.assertIsNone(B._knocks_per_hr(rec))

    def test_a_day_without_a_span_is_skipped_not_divided_by_zero(self):
        rec = _rep("No Span Tue", [120, 100, 0, 0, 0, 0],
                   [240, 0, 0, 0, 0, 0])
        self.assertAlmostEqual(B._knocks_per_hr(rec), 30.0)

    def test_a_row_pulled_before_the_spans_existed_is_blank(self):
        self.assertIsNone(B._knocks_per_hr(OLD_CACHE))

    def test_the_rep_rows_draw_it_beside_doors_per_day(self):
        rows = B.compute_rows([TWO_DAYS, STEADY, OLD_CACHE], None)
        by_name = {r[1]: r[KPH] for r in rows[1:]}
        self.assertEqual(by_name, {"Two Days": "25", "Steady": "30",
                                   "Old Cache": ""})
        self.assertEqual(B.HEADERS[KPH - 1], B.COL_DOORS_PER_DAY)


class SummaryRow(unittest.TestCase):
    def test_office_row_is_the_mean_of_the_reps_rates(self):
        row = B.totals_row([TWO_DAYS, STEADY, OLD_CACHE], None, [])
        self.assertEqual(row[KPH], "27.5")            # (25 + 30) / 2

    def test_nobody_measured_is_blank(self):
        row = B.totals_row([OLD_CACHE], None, [])
        self.assertEqual(row[KPH], "")

    def test_every_row_is_as_wide_as_the_header(self):
        rows = B.compute_rows([TWO_DAYS, STEADY], {"Sales Only": 3})
        for r in rows:
            self.assertEqual(len(r), len(B.HEADERS))

    def test_the_column_drops_out_on_a_cached_week(self):
        self.assertIn(B.COL_KNOCKS_PER_HR, B.OPTIONAL_COLUMNS)


class PullSpans(unittest.TestCase):
    def test_each_day_is_last_minus_first_in_its_own_slot(self):
        mon = dt.date(2026, 9, 7)
        firsts = [(mon, 600), (mon + dt.timedelta(days=2), 660)]
        lasts = [(mon, 840), (mon + dt.timedelta(days=2), 650),
                 (mon + dt.timedelta(days=5), 700)]
        # Mon 4h; Wed's last is before its first → 0; Sat has no first → 0.
        self.assertEqual(P._daily_spans(firsts, lasts, mon, 6),
                         [240, 0, 0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
