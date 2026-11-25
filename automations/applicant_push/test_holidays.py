"""Thanksgiving 2026: no resume pushing anywhere (Megan 2026-11-25)."""
import datetime as dt
import unittest

from automations.applicant_push.window import quiet_window


class Holidays(unittest.TestCase):
    def test_thanksgiving_is_quiet_all_day(self):
        for h in (0, 5, 6, 9, 13, 21, 23):
            self.assertTrue(quiet_window(dt.datetime(2026, 11, 26, h, 30)), h)

    def test_the_days_around_it_are_normal(self):
        self.assertFalse(quiet_window(dt.datetime(2026, 11, 25, 9, 0)))
        self.assertFalse(quiet_window(dt.datetime(2026, 11, 27, 9, 0)))
        self.assertTrue(quiet_window(dt.datetime(2026, 11, 27, 13, 0)))  # Fri pause


if __name__ == "__main__":
    unittest.main()
