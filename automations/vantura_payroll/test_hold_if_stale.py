"""Payroll holds on a DD export Tableau hasn't refreshed (2026-10-18: the
week-ending-10/18 pull was the 10/11 export unchanged, newest activation 10/10).

    python -m unittest automations.vantura_payroll.test_hold_if_stale
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

from automations.shared import tableau_freshness as tf
from automations.vantura_payroll import run as R

WEEK = dt.date(2026, 10, 18)


class HoldIfStale(unittest.TestCase):

    def _check(self, newest):
        with mock.patch.object(tf, "newest_date",
                               return_value=(newest, "cl.Activation Date")):
            R._hold_if_stale(Path("x.xlsx"), WEEK, log=lambda *_: None)

    def test_last_weeks_export_holds(self):
        with self.assertRaises(RuntimeError):
            self._check(dt.date(2026, 10, 10))

    def test_this_weeks_saturday_loads(self):
        self._check(dt.date(2026, 10, 17))

    def test_one_day_slack(self):
        self._check(dt.date(2026, 10, 16))

    def test_no_date_says_nothing(self):
        self._check(None)


if __name__ == "__main__":
    unittest.main()
