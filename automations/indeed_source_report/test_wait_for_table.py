"""The scrape waits for a slow Source Report instead of giving up after 1.8s.

Run:  python -m unittest automations.indeed_source_report.test_wait_for_table

WHAT THIS GUARDS (2026-10-02). Rafael Hidalgo (11280) failed both attempts at
01:39 with "no Source Report table came back" — a day after pulling 68 rows
fine. His post goes through _submit's "click landed during timeout" path, and
the fixed 1.8s wait scraped before his response had arrived.
"""
from __future__ import annotations

import unittest

from automations.indeed_source_report import fetch


class _Page:
    """Answers the row-count poll from a script: one entry per poll. An
    Exception entry is raised (a navigation swapping the page mid-poll)."""

    def __init__(self, counts):
        self._counts = list(counts)
        self.polls = 0
        self.slept = 0

    def evaluate(self, js):
        self.polls += 1
        v = self._counts.pop(0) if self._counts else 0
        if isinstance(v, Exception):
            raise v
        return v

    def wait_for_timeout(self, ms):
        self.slept += ms


class ASlowReportIsWaitedFor(unittest.TestCase):

    def test_table_that_arrives_late_is_found(self):
        """The 2026-10-02 shape: nothing for several polls, then the table."""
        p = _Page([0, 0, 0, 0, 0, 68, 68])
        self.assertEqual(fetch._wait_for_table(p, timeout=120000), 68)
        self.assertGreater(p.slept, 1800)

    def test_a_navigation_mid_poll_is_not_fatal(self):
        p = _Page([RuntimeError("Execution context was destroyed"), 0, 40, 40])
        self.assertEqual(fetch._wait_for_table(p, timeout=120000), 40)

    def test_a_table_still_streaming_is_not_scraped_half_done(self):
        """Rows still growing → keep polling until two counts match."""
        p = _Page([10, 300, 790, 790])
        self.assertEqual(fetch._wait_for_table(p, timeout=120000), 790)
        self.assertEqual(p.polls, 4)


class AFastReportCostsNoMoreThanBefore(unittest.TestCase):

    def test_ready_table_returns_on_the_second_poll(self):
        p = _Page([47, 47])
        self.assertEqual(fetch._wait_for_table(p, timeout=120000), 47)
        self.assertEqual(p.slept, 2000)


class ATableThatNeverComesStillEnds(unittest.TestCase):

    def test_gives_up_at_the_timeout_and_reports_zero(self):
        p = _Page([])
        self.assertEqual(fetch._wait_for_table(p, timeout=10000, poll=2000), 0)
        self.assertLessEqual(p.slept, 12000)


class TheOvernightPassGetsFiveMinutes(unittest.TestCase):

    def test_table_after_three_minutes_is_found(self):
        """The 2026-10-09 shape: Raf's 1 AM report outlives the old 120s."""
        p = _Page([0] * 90 + [230, 230])
        self.assertEqual(
            fetch._wait_for_table(p, timeout=fetch.TABLE_WAIT_MS), 230)

    def test_budget_is_wider_than_the_load_timeout(self):
        self.assertGreaterEqual(fetch.TABLE_WAIT_MS, 300000)


if __name__ == "__main__":
    unittest.main()
