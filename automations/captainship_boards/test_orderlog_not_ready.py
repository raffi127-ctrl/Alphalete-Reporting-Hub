"""An empty Monday-morning order-log export is not a failure.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.captainship_boards.test_orderlog_not_ready

WHAT THIS GUARDS (Megan 2026-08-24). Captainship Boards Daily Fill failed three
times before 05:42 on Monday 8/24 and opened "didn't finish · exit 1" in
#claudecorrections. Nothing was broken. The export window is
`monday_of(today)` → `today`; on a Monday that is a single day — today — and
today's B2B orders had not posted yet, so Tableau answered HTTP 200 with a
1-byte body and `_fetch_csv`'s `>= 1000` size check turned an empty Monday into
a crash. Retrying could not help: the retries were asking for data that did not
exist yet, which is why all three attempts returned the same 1 byte.

The guard has to be NARROW. A blanket "empty means not ready" would let a real
outage pass silently, which is far worse than a noisy morning.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.captainship_boards.run import orderlog_not_ready_yet

MON = dt.date(2026, 8, 24)          # the Monday it actually happened
EMPTY = RuntimeError("order-log export failed: status=200 bytes=1")


class NotReadyYet(unittest.TestCase):

    def test_the_real_monday_failure_is_recognised(self):
        self.assertTrue(orderlog_not_ready_yet(MON, MON, EMPTY))

    def test_a_slightly_larger_but_still_empty_body_counts(self):
        """A header-only or BOM-only export is just as empty."""
        for n in (0, 1, 3, 999):
            with self.subTest(bytes=n):
                self.assertTrue(orderlog_not_ready_yet(
                    MON, MON,
                    RuntimeError(f"order-log export failed: status=200 bytes={n}")))


class StillAFailure(unittest.TestCase):
    """Everything the guard must NOT swallow."""

    def test_a_multi_day_window_is_never_not_ready(self):
        """Tue-Sun the window spans at least one COMPLETE day, so an empty
        export there is a real problem."""
        self.assertFalse(orderlog_not_ready_yet(
            MON, MON + dt.timedelta(days=1), EMPTY))
        self.assertFalse(orderlog_not_ready_yet(
            MON, MON + dt.timedelta(days=6), EMPTY))

    def test_a_server_error_is_a_failure(self):
        for status in (401, 403, 404, 500, 503):
            with self.subTest(status=status):
                self.assertFalse(orderlog_not_ready_yet(
                    MON, MON,
                    RuntimeError(f"order-log export failed: status={status} bytes=1")))

    def test_a_full_body_is_a_failure(self):
        """200 with real content that still errored is something else entirely."""
        self.assertFalse(orderlog_not_ready_yet(
            MON, MON,
            RuntimeError("order-log export failed: status=200 bytes=48120")))

    def test_an_unrelated_exception_is_a_failure(self):
        for exc in (TimeoutError("navigation timeout"),
                    RuntimeError("Tableau auth failed"),
                    ValueError("boom"),
                    RuntimeError("")):
            with self.subTest(exc=type(exc).__name__):
                self.assertFalse(orderlog_not_ready_yet(MON, MON, exc))

    def test_a_network_timeout_on_a_monday_still_fails(self):
        """The dangerous near-miss: right day-shape, wrong reason. A timeout on
        Monday must NOT be excused as 'no orders yet'."""
        self.assertFalse(orderlog_not_ready_yet(
            MON, MON, TimeoutError("Timeout 300000ms exceeded")))


if __name__ == "__main__":
    unittest.main()
