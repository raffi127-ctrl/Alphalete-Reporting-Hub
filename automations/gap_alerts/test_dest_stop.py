"""A destination can carry a stop time; Carlos's rooms stop Saturdays at 5:30
(2026-09-27), while Raf's own window runs to 8."""
import datetime as dt
import unittest
from unittest import mock

from automations.gap_alerts import run as R, config as C


class DestStopTest(unittest.TestCase):
    CFG = {"key": "rafael", "timezone": "America/Chicago"}

    def _at(self, when):
        return mock.patch.object(C, "office_now", lambda cfg, now=None: when)

    def test_saturday_after_530_is_past(self):
        d = {"kind": "imessage", "name": "x", "sat_stop": "17:30"}
        with self._at(dt.datetime(2026, 9, 26, 17, 45)):   # Saturday
            self.assertTrue(R._past_stop(d, self.CFG))
        with self._at(dt.datetime(2026, 9, 26, 17, 15)):
            self.assertFalse(R._past_stop(d, self.CFG))

    def test_a_weekday_ignores_sat_stop(self):
        d = {"kind": "imessage", "name": "x", "sat_stop": "17:30"}
        with self._at(dt.datetime(2026, 9, 25, 19, 0)):    # Friday
            self.assertFalse(R._past_stop(d, self.CFG))

    def test_no_stop_is_never_past(self):
        with self._at(dt.datetime(2026, 9, 26, 23, 0)):
            self.assertFalse(R._past_stop({"kind": "imessage", "name": "x"}, self.CFG))

    def test_carlos_rooms_carry_it(self):
        for d in C.RAF["guests"]["Carlos Hidalgo"]:
            self.assertEqual(d.get("sat_stop"), "17:30")


if __name__ == "__main__":
    unittest.main()
