"""The Lucys push on Carlos's schedule (Megan 2026-10-28): 5:30 AM-10 PM,
each office every 15 min, and before 7:00 never while the Lucy's own 4am run
is busy. Pure logic; no browser, nothing is pushed."""
import datetime as dt
import os
import tempfile
import time
import unittest

from automations.applicant_push import window as W


def at(h, m):
    return dt.datetime(2026, 10, 29, h, m)


class CarlosSchedule(unittest.TestCase):

    def setUp(self):
        self.stamp = os.path.join(tempfile.mkdtemp(), "stamp")

    def test_hours(self):
        self.assertFalse(W.in_hours(at(5, 29)))
        self.assertTrue(W.in_hours(at(5, 30)))
        self.assertTrue(W.in_hours(at(22, 0)))
        self.assertFalse(W.in_hours(at(22, 2)))

    def test_early_waits_for_the_4am_run(self):
        ok, why = W.gate("24065", self.stamp, at(5, 40), lambda: True)
        self.assertFalse(ok)
        self.assertIn("4am", why)
        self.assertTrue(W.gate("24065", self.stamp, at(5, 40), lambda: False)[0])

    def test_unknown_batch_state_waits(self):
        self.assertFalse(W.gate("24065", self.stamp, at(6, 0), lambda: None)[0])

    def test_after_7_the_batch_is_not_consulted(self):
        def boom():
            raise AssertionError("must not be asked")
        self.assertTrue(W.gate("24065", self.stamp, at(9, 0), boom)[0])

    def test_every_15_minutes_per_office(self):
        open(self.stamp, "w").write(str(time.time() - 10 * 60))
        self.assertFalse(W.gate("24065", self.stamp, at(9, 0))[0])
        open(self.stamp, "w").write(str(time.time() - 15 * 60))
        self.assertTrue(W.gate("24065", self.stamp, at(9, 0))[0])

    def test_same_as_carlos_relay(self):
        from automations.icd_alerts import resume_push as rp
        self.assertEqual((W.DAY_START, W.DAY_END, W.EVERY_MINUTES),
                         (rp.DAY_START, rp.DAY_END, rp.EVERY_MINUTES))


if __name__ == "__main__":
    unittest.main()
