"""The sales board's hours and its 2am catch-up. No network, no browser."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import config as C
from automations.icd_alerts import sales_closeout as SC


def at(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


class SalesWindowTests(unittest.TestCase):
    def test_saturday_evening_is_read_now(self):
        # The gap the morning check found: Saturdays stopped at 17:00.
        self.assertTrue(C.in_sales_window(at("2026-09-19 20:45")))
        self.assertFalse(C.in_selling_window(at("2026-09-19 20:45")))

    def test_sunday_is_read(self):
        self.assertTrue(C.in_sales_window(at("2026-09-20 15:00")))

    def test_noon_to_midnight(self):
        self.assertFalse(C.in_sales_window(at("2026-09-21 11:59")))
        self.assertTrue(C.in_sales_window(at("2026-09-21 12:00")))
        self.assertTrue(C.in_sales_window(at("2026-09-21 23:59")))
        self.assertFalse(C.in_sales_window(at("2026-09-22 00:30")))


class CatchUpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(
            SC, "STATE", Path(self.tmp.name) / "sales_closeout.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_not_before_two(self):
        self.assertIsNone(SC.due(at("2026-09-22 01:59")))

    def test_yesterday_after_two(self):
        self.assertEqual(SC.due(at("2026-09-22 02:05")), dt.date(2026, 9, 21))

    def test_sunday_is_closed_out_too(self):
        # Seven days a week: Monday 2am finalises Sunday.
        self.assertEqual(SC.due(at("2026-09-21 02:05")), dt.date(2026, 9, 20))

    def test_once_done_it_stops(self):
        seen = []
        SC.maybe_run(lambda d: seen.append(d) or 0, now=at("2026-09-22 02:05"),
                     log=lambda *_: None)
        SC.maybe_run(lambda d: seen.append(d) or 0, now=at("2026-09-22 02:20"),
                     log=lambda *_: None)
        self.assertEqual(seen, [dt.date(2026, 9, 21)])

    def test_gives_up_after_the_cap(self):
        calls = []
        for i in range(SC.MAX_ATTEMPTS + 3):
            SC.maybe_run(lambda d: calls.append(d) or 1,
                         now=at("2026-09-22 02:05") + dt.timedelta(minutes=i),
                         log=lambda *_: None)
        self.assertEqual(len(calls), SC.MAX_ATTEMPTS)

    def test_a_crash_never_escapes(self):
        def boom(_d):
            raise RuntimeError("SaraPlus is down")
        self.assertIsNone(SC.maybe_run(boom, now=at("2026-09-22 02:05"),
                                       log=lambda *_: None))


if __name__ == "__main__":
    unittest.main()
