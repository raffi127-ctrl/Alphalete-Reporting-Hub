"""The day's baseline pass runs ONCE, and credit checks count as the day
having started.

Until 2026-10-10 the baseline test was "are there sales stored for today",
and credit checks are stored apart (state '_records'), so every sweep before
the day's first sale was another baseline: early credit-check pings and the
first sale's hype were dropped (10/8: four baselines, 12:01-13:35).
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.alphalete_sales_board import state as S

DAY = dt.date(2026, 10, 17)
ZERO = {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 0}


def _sale(n=1):
    return dict(ZERO, Int=n)


def sweep(data, today, records):
    """What run.sweep decides, at the state level: (baseline, sales that get
    hype, credit checks that get a ping, new state)."""
    gained = S.deltas(data, DAY, today)
    rec_gained = S.record_deltas(data, DAY, records)
    baseline = not S.day_started(data, DAY)
    hype = {} if baseline else gained
    pings = {} if baseline else rec_gained
    data = S.prune(S.remember(data, DAY, today, records))
    return baseline, hype, pings, data


class BaselineOnce(unittest.TestCase):
    def test_first_sweep_is_the_baseline_and_only_the_first(self):
        b1, hype, pings, data = sweep({}, {"Ann": _sale()}, {"Ann": 2})
        self.assertTrue(b1)
        self.assertEqual((hype, pings), ({}, {}))
        b2, _, _, data = sweep(data, {"Ann": _sale()}, {"Ann": 2})
        self.assertFalse(b2)

    def test_credit_check_before_any_sale_starts_the_day(self):
        # Sweep 1: credit checks only -> the single baseline.
        b1, _, _, data = sweep({}, {}, {"Bo": 1})
        self.assertTrue(b1)
        self.assertTrue(S.day_started(data, DAY))
        # Sweep 2: a NEW credit check gets its ping (was dropped as baseline).
        b2, hype, pings, data = sweep(data, {}, {"Bo": 1, "Cy": 1})
        self.assertFalse(b2)
        self.assertEqual(pings, {"Cy": 1})
        # Sweep 3: the day's FIRST sale gets its hype.
        b3, hype, pings, data = sweep(data, {"Cy": _sale()}, {"Bo": 1, "Cy": 1})
        self.assertFalse(b3)
        self.assertEqual(hype, {"Cy": {"Int": 1}})

    def test_an_empty_first_sweep_still_starts_the_day(self):
        # Saturday 10:30, nobody has sold yet: the 10:35 first sale is news.
        b1, _, _, data = sweep({}, {}, {})
        self.assertTrue(b1)
        b2, hype, _, _ = sweep(data, {"Dee": _sale()}, {})
        self.assertFalse(b2)
        self.assertEqual(hype, {"Dee": {"Int": 1}})

    def test_state_from_before_the_marker_is_not_rebaselined(self):
        # A state file written by the old code mid-day: sales on file, no
        # '_started'. Deploying must not make the next sweep a baseline.
        old_sales = {DAY.isoformat(): {"Ann": _sale()}}
        self.assertTrue(S.day_started(old_sales, DAY))
        old_checks = {"_records": {DAY.isoformat(): {"Bo": 1}}}
        self.assertTrue(S.day_started(old_checks, DAY))

    def test_marker_survives_prune_and_is_per_day(self):
        _, _, _, data = sweep({}, {}, {})
        self.assertIn("_started", S.prune(data))
        self.assertFalse(S.day_started(data, DAY + dt.timedelta(days=1)))


if __name__ == "__main__":
    unittest.main()
