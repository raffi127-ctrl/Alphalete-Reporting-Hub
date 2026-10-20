"""A low day that has stopped moving is a real day (2026-10-20: AT&T Monday
1,081 = 86% of its 4-week avg, unchanged 09:01-11:38, held 15 captainship
reports + 2 country boards all morning).

    python -m unittest automations.tableau_screenshots.test_long_settle
"""
from __future__ import annotations

import unittest

from automations.tableau_screenshots import freshness as F

REAL = [["2026-10-20T09:01:44", 1081.0], ["2026-10-20T10:46:48", 1081.0],
        ["2026-10-20T10:58:26", 1081.0], ["2026-10-20T11:12:00", 1081.0],
        ["2026-10-20T11:25:14", 1081.0], ["2026-10-20T11:38:20", 1081.0]]


class LongSettle(unittest.TestCase):

    def test_the_10_20_morning_clears(self):
        self.assertGreaterEqual(F.settled_for_minutes(REAL, 1081.0),
                                F.LONG_SETTLE_MIN)

    def test_a_growing_day_never_clears(self):
        growing = [["2026-10-20T06:00:00", 600.0], ["2026-10-20T07:00:00", 800.0],
                   ["2026-10-20T08:00:00", 956.0], ["2026-10-20T09:00:00", 1050.0]]
        self.assertEqual(F.settled_for_minutes(growing, 1050.0), 0.0)

    def test_only_the_latest_flat_run_counts(self):
        s = [["2026-10-20T06:00:00", 900.0], ["2026-10-20T08:00:00", 900.0],
             ["2026-10-20T09:00:00", 1000.0], ["2026-10-20T09:20:00", 1000.0]]
        self.assertEqual(F.settled_for_minutes(s, 1000.0), 20.0)

    def test_one_sample_is_not_settled(self):
        self.assertEqual(F.settled_for_minutes(REAL[:1], 1081.0), 0.0)


if __name__ == "__main__":
    unittest.main()
