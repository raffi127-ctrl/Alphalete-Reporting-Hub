"""Raf 2026-09-28: "Keep the praise one." Raf's window runs to 10pm, so the
day's positive call-out moved from the window's last tick to the last tick
before the 8:30 call-out cutoff (5pm on Saturday)."""
import datetime as dt
import unittest

from automations.gap_alerts import run as R

CFG = {"key": "rafael", "day_end": "22:00", "sat_end": "20:00"}


class PraiseTickFollowsTheCutoff(unittest.TestCase):
    def test_weekday_is_the_815_tick(self):
        self.assertTrue(R._praise_tick(CFG, "rafael", dt.datetime(2026, 9, 28, 20, 15)))
        self.assertFalse(R._praise_tick(CFG, "rafael", dt.datetime(2026, 9, 28, 21, 45)))
        self.assertFalse(R._praise_tick(CFG, "rafael", dt.datetime(2026, 9, 28, 20, 30)))

    def test_saturday_is_the_445_tick(self):
        self.assertTrue(R._praise_tick(CFG, "rafael", dt.datetime(2026, 10, 3, 16, 45)))
        self.assertFalse(R._praise_tick(CFG, "rafael", dt.datetime(2026, 10, 3, 19, 45)))

    def test_sunday_never(self):
        self.assertFalse(R._praise_tick(CFG, "rafael", dt.datetime(2026, 10, 4, 20, 15)))


if __name__ == "__main__":
    unittest.main()
