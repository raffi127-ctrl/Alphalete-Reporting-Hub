"""Megan 2026-10-07: "I like 1st sale call out and back to back sale call out"."""
import datetime as dt
import unittest
from unittest import mock

from automations.shared import sale_hype as H

DAY = dt.date(2026, 10, 7)
NOW = dt.datetime(2026, 10, 7, 15, 0)


class FirstSaleTest(unittest.TestCase):
    def test_first_rep_gets_the_first_sale_line(self):
        with mock.patch.object(H, "recent_lines", return_value=[]), \
             mock.patch.object(H, "record_lines", lambda *a, **k: None), \
             mock.patch.object(H, "record_sale_times", lambda *a, **k: None), \
             mock.patch.object(H, "last_sale_at", return_value=None):
            out = H.hype_batch(["BRIANA BAEZ ACOSTA", "ASIA MOSLEY"],
                               {"BRIANA BAEZ ACOSTA": {"Int": 1}, "ASIA MOSLEY": {"Int": 1}},
                               DAY, "att", room="tre", office_first=True, now=NOW)
        self.assertEqual(len(out), 2)
        self.assertIn("Briana", out[0])
        self.assertTrue(any(out[0] == t.format(first="Briana") for t in H.FIRST_SALE_LINES), out[0])
        self.assertNotIn("Asia is OTB", out[1])

    def test_not_first_means_regular_lines(self):
        with mock.patch.object(H, "recent_lines", return_value=[]), \
             mock.patch.object(H, "record_lines", lambda *a, **k: None), \
             mock.patch.object(H, "record_sale_times", lambda *a, **k: None), \
             mock.patch.object(H, "last_sale_at", return_value=None):
            out = H.hype_batch(["BRIANA BAEZ ACOSTA"], {"BRIANA BAEZ ACOSTA": {"Int": 1}},
                               DAY, "att", room="tre", office_first=False, now=NOW)
        self.assertFalse(any(out[0] == t.format(first="Briana") for t in H.FIRST_SALE_LINES))


class BackToBackTest(unittest.TestCase):
    def test_a_sale_inside_thirty_minutes_is_a_streak(self):
        with mock.patch.object(H, "recent_lines", return_value=[]), \
             mock.patch.object(H, "record_lines", lambda *a, **k: None), \
             mock.patch.object(H, "record_sale_times", lambda *a, **k: None), \
             mock.patch.object(H, "last_sale_at", return_value=NOW - dt.timedelta(minutes=17)):
            out = H.hype_batch(["MOHAMMAD SHAIKH"], {"MOHAMMAD SHAIKH": {"Int": 2}},
                               DAY, "att", room="jamis", now=NOW)
        self.assertIn("17", out[0])
        self.assertIn("Mohammad", out[0])

    def test_an_hour_apart_is_not(self):
        with mock.patch.object(H, "recent_lines", return_value=[]), \
             mock.patch.object(H, "record_lines", lambda *a, **k: None), \
             mock.patch.object(H, "record_sale_times", lambda *a, **k: None), \
             mock.patch.object(H, "last_sale_at", return_value=NOW - dt.timedelta(minutes=61)):
            out = H.hype_batch(["MOHAMMAD SHAIKH"], {"MOHAMMAD SHAIKH": {"Int": 2}},
                               DAY, "att", room="jamis", now=NOW)
        self.assertFalse(any("Two" in out[0] or "Back to back" in out[0] or "streak" in out[0] for _ in [0]))

    def test_sale_times_are_remembered_per_room(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(H, "SALE_TIMES_PATH", pathlib.Path(d) / "t.json"):
                H.record_sale_times(DAY, "jamis", ["MOHAMMAD SHAIKH"], NOW)
                self.assertEqual(H.last_sale_at(DAY, "jamis", "MOHAMMAD SHAIKH"), NOW)
                self.assertIsNone(H.last_sale_at(DAY, "tre", "MOHAMMAD SHAIKH"))
                self.assertIsNone(H.last_sale_at(DAY, "jamis", "SOMEONE ELSE"))


if __name__ == "__main__":
    unittest.main()
