"""A slow ownerville page costs ONE of the three navigations, not the office.

2026-09-20, #claudecorrections-and-requests: "Colten Wright: weekly pull FAILED
— TimeoutError: Page.goto: Timeout 25000ms exceeded". Both knock pulls already
re-navigated up to three times, but only around a grid that never built: the
`page.goto` sat in front of the try, so a navigation timeout raised past the
loop with every attempt unused and that owner's board came back as a yellow
'could not be captured' box — which holds the captain's whole email (run.py
guard 2).

    python -m unittest automations.weekly_knock_dispositions.test_navigate_retry
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.total_knocks import pull as daily
from automations.weekly_knock_dispositions import pull as weekly


class FakePage:
    """Times out on the first `fail_gotos` navigations, then loads."""

    def __init__(self, fail_gotos=0, grid=True):
        self.fail_gotos = fail_gotos
        self.grid = grid
        self.gotos = 0

    def goto(self, url, **kw):
        self.gotos += 1
        if self.gotos <= self.fail_gotos:
            raise TimeoutError("Page.goto: Timeout 25000ms exceeded")

    def wait_for_selector(self, sel, **kw):
        if not self.grid:
            raise TimeoutError("selector never appeared")

    def locator(self, sel):
        raise RuntimeError("no length picker")      # the caller swallows this

    def wait_for_load_state(self, *a, **kw):
        pass


DAY = dt.date(2026, 9, 19)


class WeeklyNavigateTests(unittest.TestCase):

    def test_one_slow_load_is_retried_not_fatal(self):
        page = FakePage(fail_gotos=1)
        weekly._navigate_day(page, "RQST", DAY, verbose=False)
        self.assertEqual(page.gotos, 2)

    def test_every_navigation_timing_out_still_raises(self):
        page = FakePage(fail_gotos=3)
        with self.assertRaises(TimeoutError):
            weekly._navigate_day(page, "RQST", DAY, verbose=False)
        self.assertEqual(page.gotos, 3)

    def test_a_stalled_grid_still_falls_through_to_the_scrape(self):
        # Unchanged contract: the page loads, the grid never builds, and the
        # scrape reports it with the live-headers diagnostic.
        page = FakePage(grid=False)
        weekly._navigate_day(page, "RQST", DAY, verbose=False)
        self.assertEqual(page.gotos, 3)


class DailyNavigateTests(unittest.TestCase):

    def test_one_slow_load_is_retried_not_fatal(self):
        page = FakePage(fail_gotos=1)
        daily._navigate(page, "RQST", "09/19/2026")
        self.assertEqual(page.gotos, 2)

    def test_every_navigation_timing_out_still_raises(self):
        page = FakePage(fail_gotos=3)
        with self.assertRaises(TimeoutError):
            daily._navigate(page, "RQST", "09/19/2026")

    def test_a_stalled_grid_still_falls_through_to_the_scrape(self):
        page = FakePage(grid=False)
        daily._navigate(page, "RQST", "09/19/2026")
        self.assertEqual(page.gotos, 3)


if __name__ == "__main__":
    unittest.main()
