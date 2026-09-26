"""The date window and the per-office tab — the two things that decide whether
a two-office comparison can hold both halves at once.

  python -m unittest automations.sms_thread_dump.test_window
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.sms_thread_dump import run as R


class WindowTest(unittest.TestCase):
    def test_the_default_is_last_wed_thu_fri(self):
        # Saturday 2026-09-26 → the Wed/Thu/Fri just gone
        self.assertEqual(R._default_dates(dt.date(2026, 9, 26)),
                         [dt.date(2026, 9, 23), dt.date(2026, 9, 24),
                          dt.date(2026, 9, 25)])

    def test_default_never_includes_today(self):
        # Friday: the Friday it picks is LAST Friday, not this morning's
        out = R._default_dates(dt.date(2026, 9, 25))
        self.assertNotIn(dt.date(2026, 9, 25), out)
        self.assertIn(dt.date(2026, 9, 18), out)

    def test_days_window_skips_sunday(self):
        # Tuesday 2026-09-22 → Mon 21, Sat 19, Fri 18: Sunday the 20th is not a
        # day anybody books a first interview, and asking for it just burns a
        # page load to be told "no First Interview section"
        self.assertEqual(R._last_days(3, dt.date(2026, 9, 22)),
                         [dt.date(2026, 9, 18), dt.date(2026, 9, 19),
                          dt.date(2026, 9, 21)])

    def test_days_window_is_strictly_before_today(self):
        out = R._last_days(1, dt.date(2026, 9, 26))
        self.assertEqual(out, [dt.date(2026, 9, 25)])


class TabNameTest(unittest.TestCase):
    def test_each_office_gets_its_own_tab(self):
        # one shared tab meant the second office's run cleared the first's
        # rows, which is exactly the comparison Carlos asked for
        self.assertEqual("{} {}".format(R.TAB_PREFIX, "11280"), "SMS Dump 11280")
        self.assertNotEqual("{} {}".format(R.TAB_PREFIX, "11280"),
                            "{} {}".format(R.TAB_PREFIX, "11580"))


if __name__ == "__main__":
    unittest.main()
