"""Early-week ABP with no new internet sales yet is "nothing to fill", not a
failure (2026-10-20: Cyrus + Salik, 22 reps each in the This-Week view, no ABP %
on a Tuesday morning; the same on Tue 10/06).

    python -m unittest automations.new_internet_abp.test_nothing_yet
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.new_internet_abp.run import nothing_yet_this_week as N

MON, TUE, WED = dt.date(2026, 10, 19), dt.date(2026, 10, 20), dt.date(2026, 10, 21)


class NothingYet(unittest.TestCase):

    def test_tuesday_in_view_with_reps(self):
        self.assertTrue(N(True, TUE, 22))
        self.assertTrue(N(True, MON, 22))

    def test_wednesday_still_fails(self):
        self.assertFalse(N(True, WED, 22))

    def test_not_in_view_still_fails(self):
        self.assertFalse(N(False, TUE, 22))

    def test_no_reps_still_fails(self):
        self.assertFalse(N(True, TUE, 0))


if __name__ == "__main__":
    unittest.main()
