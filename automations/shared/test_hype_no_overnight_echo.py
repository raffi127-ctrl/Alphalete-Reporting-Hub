"""The first sale of a morning must not echo the last line of the night
before (Roshan's channel, 2026-09-21 8:01 PM -> 2026-09-22 10:50 AM)."""
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.shared import sale_hype as H


class OvernightEchoTest(unittest.TestCase):
    def setUp(self):
        self.path = pathlib.Path(tempfile.mkdtemp()) / "recent.json"
        self.p = mock.patch.object(H, "RECENT_LINES_PATH", self.path)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_yesterdays_lines_still_count_as_recent(self):
        y, t = dt.date(2026, 9, 21), dt.date(2026, 9, 22)
        H.record_lines(y, "roshan", ["{first} ATE. Everybody else picking crumbs"])
        self.assertIn("{first} ATE. Everybody else picking crumbs",
                      H.recent_lines(t, "roshan"))

    def test_todays_lines_come_first(self):
        y, t = dt.date(2026, 9, 21), dt.date(2026, 9, 22)
        H.record_lines(y, "roshan", ["old"])
        H.record_lines(t, "roshan", ["new"])
        self.assertEqual(H.recent_lines(t, "roshan")[:2], ["new", "old"])

    def test_two_days_back_is_forgotten(self):
        H.record_lines(dt.date(2026, 9, 20), "roshan", ["stale"])
        self.assertEqual(H.recent_lines(dt.date(2026, 9, 22), "roshan"), [])

    def test_another_room_is_untouched(self):
        H.record_lines(dt.date(2026, 9, 21), "roshan", ["x"])
        self.assertEqual(H.recent_lines(dt.date(2026, 9, 22), "aya"), [])


if __name__ == "__main__":
    unittest.main()
