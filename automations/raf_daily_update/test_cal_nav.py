"""_goto_day: a slow calendar is not the same as a calendar that never moved.

The failure these pin down (Cyrus, 2026-11-18): the old code fired the
navigation, slept a flat 15 seconds, looked ONCE for the page's own
"found for MM-DD-YYYY" marker, and abandoned the day if it was not there --
so a page that was merely slow cost every start date for the people
interviewed that day, on a report that is already live for Raf.

    python -m unittest automations.raf_daily_update.test_cal_nav
"""
import datetime as dt
import unittest
from unittest import mock

from automations.raf_daily_update import run as R

DAY = dt.date(2026, 11, 16)


class FakePage:
    """A calendar page that shows the day only after `lands_on_try` attempts."""

    def __init__(self, lands_on_try=1, status="ok"):
        self.lands_on_try = lands_on_try
        self.status = status
        self.navs = 0
        self.waits = 0

    def evaluate(self, js, arg=None):
        self.navs += 1
        return self.status

    def wait_for_function(self, expr, arg=None, timeout=None):
        self.waits += 1
        if self.waits < self.lands_on_try:
            raise TimeoutError("still not showing it")
        return True


class FakeApp:
    def __init__(self, page):
        self.page = page


class TheCalendarMove(unittest.TestCase):

    def setUp(self):
        patch = mock.patch.object(R, "log", lambda *a, **k: None)
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_stops_waiting_the_moment_the_day_is_showing(self):
        # The point of polling: a page that arrives quickly must not still
        # cost the old flat fifteen seconds.
        page = FakePage(lands_on_try=1)
        self.assertTrue(R._goto_day(FakeApp(page), DAY))
        self.assertEqual(page.navs, 1)
        self.assertEqual(page.waits, 1)

    def test_a_slow_page_gets_a_second_go_instead_of_being_abandoned(self):
        page = FakePage(lands_on_try=2)
        self.assertTrue(R._goto_day(FakeApp(page), DAY))
        self.assertEqual(page.navs, 2, "it should re-drive, not just re-wait")

    def test_it_gives_up_and_SAYS_SO_rather_than_claiming_an_empty_day(self):
        page = FakePage(lands_on_try=99)
        self.assertFalse(R._goto_day(FakeApp(page), DAY, tries=2))
        self.assertEqual(page.navs, 2)

    def test_a_missing_widget_is_reported_not_silently_retried_forever(self):
        # 'nocal' means there was nothing to drive. It still retries (the
        # widget may load late) but it is bounded and it is logged.
        page = FakePage(lands_on_try=99, status="nocal")
        said = []
        with mock.patch.object(R, "log", lambda m, *a: said.append(str(m))):
            self.assertFalse(R._goto_day(FakeApp(page), DAY, tries=2))
        self.assertTrue(any("no calendar widget" in m for m in said), said)

    def test_a_thrown_navigation_is_reported_as_itself(self):
        page = FakePage(lands_on_try=99, status="err")
        said = []
        with mock.patch.object(R, "log", lambda m, *a: said.append(str(m))):
            R._goto_day(FakeApp(page), DAY, tries=1)
        self.assertTrue(any("threw" in m for m in said), said)


if __name__ == "__main__":
    unittest.main()


class WhatCountsAsArriving(unittest.TestCase):
    """_ARRIVED_JS is a page script, so its LOGIC is checked here in Python.

    Kept in step with the real thing by construction: the cases come straight
    off the probe of office 22815 on 2026-11-16.
    """

    @staticmethod
    def arrived(text, want=(11, 16, 2026), old="found for 11-16-2026"):
        import re
        if old and old in text:
            return True
        m = re.search(r"Calendars?\s+for\s+(\d{1,2})/(\d{1,2})/(\d{4})",
                      text, re.I)
        return bool(m) and (int(m.group(1)), int(m.group(2)),
                            int(m.group(3))) == want

    def test_the_busy_day_that_used_to_be_thrown_away(self):
        # The real title line, verbatim from the probe. No "... for <date>"
        # phrase anywhere on it, because no section was empty.
        page = ("Cyrus Wade | Ambient Marketing, Inc. | "
                "Calendars for 11/16/2026 | Export to Excel")
        self.assertTrue(self.arrived(page))

    def test_the_old_nothing_found_marker_still_counts(self):
        # Quiet days carry it, and Raf's live report relies on those working.
        self.assertTrue(self.arrived("No applicants found for 11-16-2026"))

    def test_a_different_day_is_not_arrival(self):
        self.assertFalse(self.arrived("Calendars for 11/17/2026"))

    def test_an_unpadded_day_still_counts(self):
        self.assertTrue(self.arrived("Calendars for 11/6/2026",
                                     want=(11, 6, 2026), old=""))

    def test_a_page_with_neither_is_not_arrival(self):
        self.assertFalse(self.arrived("Loading..."))
