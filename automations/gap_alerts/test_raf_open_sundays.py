"""Raf (2026-10-04): his knock boards run Sun 10/4 and Sun 10/11 until 7pm
Central, then Sunday is off again. Only his office; everyone else keeps their
own Sunday rule."""
import datetime as dt
import unittest

from automations.gap_alerts import config as C

RAF = dict(C.RAF)
OTHER = {"key": "someone", "tz": C.DEFAULT_TZ}


class RafsOpenSundays(unittest.TestCase):
    def test_raf_is_open_this_sunday_until_7pm(self):
        self.assertTrue(C.in_office_window(RAF, dt.datetime(2026, 10, 4, 12, 0)))
        self.assertTrue(C.in_office_window(RAF, dt.datetime(2026, 10, 4, 18, 59)))
        self.assertFalse(C.in_office_window(RAF, dt.datetime(2026, 10, 4, 19, 1)))
        self.assertFalse(C.in_office_window(RAF, dt.datetime(2026, 10, 4, 9, 0)))

    def test_and_next_sunday(self):
        self.assertTrue(C.in_office_window(RAF, dt.datetime(2026, 10, 11, 15, 0)))

    def test_then_sunday_is_off_again(self):
        self.assertFalse(C.in_office_window(RAF, dt.datetime(2026, 10, 18, 15, 0)))
        self.assertFalse(C.in_office_window(RAF, dt.datetime(2026, 9, 27, 15, 0)))

    def test_nobody_else_opens(self):
        self.assertFalse(C.in_office_window(OTHER, dt.datetime(2026, 10, 4, 15, 0)))

    def test_weekdays_unchanged(self):
        self.assertTrue(C.in_office_window(RAF, dt.datetime(2026, 10, 5, 15, 0)))
        self.assertFalse(C.in_office_window(RAF, dt.datetime(2026, 10, 5, 23, 0)))

    def test_the_label_says_so(self):
        self.assertIn("7:00 PM", C.office_window_label(RAF, dt.datetime(2026, 10, 4, 12, 0)))

    def test_the_wrapper_wakes_on_both_dates(self):
        import pathlib
        sh = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "gap_alerts_5min.sh"
        text = sh.read_text()
        for d in C.RAF_OPEN_SUNDAYS:
            self.assertIn(d, text)


if __name__ == "__main__":
    unittest.main()
