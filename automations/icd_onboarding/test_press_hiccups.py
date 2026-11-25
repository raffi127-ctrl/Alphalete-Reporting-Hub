"""A timeout gets one more pass before the corrections channel hears of it
(Eve 2026-11-25, raf: Jerry Esebanme + Kameron Frazier)."""
import datetime as dt
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_onboarding import press_hiccups as H
from automations.icd_onboarding import presses as P

T0 = dt.datetime(2026, 11, 24, 20, 0)
REAL = ("TimeoutError: Locator.wait_for: Timeout 60000ms exceeded.\n"
        "Call log:\n  - waiting for locator(\".dataTables_filter input\")"
        "\n    - waiting for navigation to finish...")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(H, "PATH", Path(self.tmp.name) / "h.json")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)


class WhatIsAHiccup(unittest.TestCase):
    def test_the_real_error_from_the_ticket(self):
        self.assertTrue(H.is_hiccup(REAL))

    def test_ownervilles_own_answers_are_not(self):
        for said in ("not every section is done — BACKGROUND CHECK=PENDING",
                     "confirm box would not tick",
                     "not found in OwnerVille"):
            self.assertFalse(H.is_hiccup(said), said)


class TwiceInARow(Base):
    def test_first_timeout_is_held(self):
        self.assertEqual(H.settle("raf", "owner submit", ["Jerry"], [],
                                  now=T0), [])

    def test_second_timeout_alerts(self):
        H.settle("raf", "owner submit", ["Jerry"], [], now=T0)
        got = H.settle("raf", "owner submit", ["Jerry"], [],
                       now=T0 + dt.timedelta(hours=1))
        self.assertEqual(got, ["Jerry"])

    def test_a_clean_pass_in_between_resets(self):
        H.settle("raf", "owner submit", ["Jerry"], [], now=T0)
        H.settle("raf", "owner submit", [], ["Jerry"],
                 now=T0 + dt.timedelta(hours=1))
        got = H.settle("raf", "owner submit", ["Jerry"], [],
                       now=T0 + dt.timedelta(hours=2))
        self.assertEqual(got, [])

    def test_an_old_timeout_does_not_count(self):
        H.settle("raf", "owner submit", ["Jerry"], [], now=T0)
        got = H.settle("raf", "owner submit", ["Jerry"], [],
                       now=T0 + dt.timedelta(hours=H.WINDOW_H + 1))
        self.assertEqual(got, [])

    def test_offices_and_presses_are_separate(self):
        H.settle("raf", "owner submit", ["Jerry"], [], now=T0)
        later = T0 + dt.timedelta(hours=1)
        self.assertEqual(H.settle("algemar", "owner submit", ["Jerry"], [],
                                  now=later), [])
        self.assertEqual(H.settle("raf", "uid", ["Jerry"], [], now=later), [])


class WiredIntoThePress(unittest.TestCase):
    def test_press_holds_timeouts_before_alerting(self):
        src = inspect.getsource(P._press)
        self.assertIn("HIC.is_hiccup(detail)", src)
        self.assertIn("HIC.settle(", src)
        # the hiccup check runs before the refusal is counted as a failure
        self.assertLess(src.index("HIC.is_hiccup(detail)"),
                        src.index("not is_not_ready(detail)"))

    def test_a_clean_pass_still_clears_old_hiccups(self):
        src = inspect.getsource(P._press)
        self.assertIn("HIC.settle(office_key, what, [], reached)", src)


if __name__ == "__main__":
    unittest.main()
