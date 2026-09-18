"""The office loop's retry-once, and the guard that stops it duplicating rows.

2026-09-17: the 8pm run lost Khalil Mansour, Roshan Amin Ahmad and Isaiah
Revelle to three separate `Page.goto: Timeout 30000ms exceeded` while the other
13 offices synced on the same warm session. One bad page load cost each of them
the night. The loop now retries an office once — but ONLY if it never reached a
write, because the Call List and 2R Retention both append with no de-dupe and a
retry after a write duplicates rows in Francia's sheet.
"""
import datetime as dt
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from automations.applicant_tracker import config, run as R


@contextmanager
def _fake_session():
    yield object()


class _Harness:
    """Drive R.run() with every side effect stubbed but the office loop real."""

    def __init__(self, phase, office_ids, behaviour):
        self.phase = phase
        self.office_ids = office_ids
        self.behaviour = behaviour        # office_id -> list of callables
        self.calls = []                   # (office_id, attempt_index)
        self.finish = None                # kwargs _finish was called with

    def _office(self, *a, **kw):
        # Both _morning_office and _evening_office put office_id 4th/3rd
        # positionally; pull it out of whichever shape arrived.
        office_id = a[3] if self.phase == "morning" else a[2]
        clock = kw.get("clock") or a[-1]
        n = sum(1 for o, _ in self.calls if o == office_id)
        self.calls.append((office_id, n))
        step = self.behaviour[office_id][min(n, len(self.behaviour[office_id]) - 1)]
        step(clock)

    def _capture_finish(self, phase, total, **kw):
        self.finish = kw

    def go(self):
        with mock.patch.object(config, "OFFICE_IDS", self.office_ids), \
             mock.patch.object(R.sheets, "open_tab", lambda *_a, **_k: object()), \
             mock.patch.object(R, "session", _fake_session), \
             mock.patch.object(R, "_start_watchdog", lambda _r: None), \
             mock.patch.object(R, "_morning_office", self._office), \
             mock.patch.object(R, "_evening_office", self._office), \
             mock.patch.object(R, "_finish", self._capture_finish):
            R.run(self.phase, target=dt.date(2026, 9, 17))
        return self


def _ok(_clock):
    pass


def _boom(_clock):
    raise RuntimeError("Page.goto: Timeout 30000ms exceeded")


def _wrote_then_boom(clock):
    clock.wrote = True
    raise RuntimeError("Page.goto: Timeout 30000ms exceeded")


class OfficeRetryTests(unittest.TestCase):

    def test_transient_before_any_write_is_retried_and_recovers(self):
        h = _Harness("evening", ["19833"], {"19833": [_boom, _ok]}).go()
        self.assertEqual(h.calls, [("19833", 0), ("19833", 1)])
        self.assertEqual(h.finish["failed"], [],
                         "an office that recovered on retry must not be "
                         "reported as a gap")

    def test_still_failing_after_retry_is_reported_once(self):
        h = _Harness("evening", ["19833"], {"19833": [_boom, _boom]}).go()
        self.assertEqual(len(h.calls), 2, "retried exactly once, not a loop")
        self.assertEqual(h.finish["failed"], ["19833"])

    def test_office_that_already_wrote_is_never_retried(self):
        """The whole point of the guard: a second append would duplicate rows."""
        h = _Harness("evening", ["19833"], {"19833": [_wrote_then_boom, _ok]}).go()
        self.assertEqual(h.calls, [("19833", 0)],
                         "an office that reached a write must NOT be re-run — "
                         "the Call List / 2R Retention appends have no de-dupe")
        self.assertEqual(h.finish["failed"], ["19833"])

    def test_morning_write_guard_holds_too(self):
        h = _Harness("morning", ["11901"], {"11901": [_wrote_then_boom, _ok]}).go()
        self.assertEqual(h.calls, [("11901", 0)])
        self.assertEqual(h.finish["failed"], ["11901"])

    def test_retry_does_not_disturb_the_other_offices(self):
        """The 2026-09-17 shape: 3 of 16 error, the rest are untouched."""
        ids = ["11280", "11901", "11580", "19833", "19717"]
        h = _Harness("evening", ids, {
            "11280": [_ok], "11580": [_ok],
            "11901": [_boom, _ok], "19833": [_boom, _ok], "19717": [_boom, _ok],
        }).go()
        self.assertEqual(h.finish["failed"], [])
        self.assertEqual([o for o, n in h.calls if n == 1],
                         ["11901", "19833", "19717"])

    def test_no_access_on_retry_is_classed_as_no_access_not_failed(self):
        def _denied(_clock):
            raise R.OfficeNotAvailable("not in this login's office list")
        h = _Harness("evening", ["19717"], {"19717": [_boom, _denied]}).go()
        self.assertEqual(h.finish["no_access"], ["19717"])
        self.assertEqual(h.finish["failed"], [])


if __name__ == "__main__":
    unittest.main()


class RetryBudgetTests(unittest.TestCase):
    """A retry spends the SWEEP's budget. Once it is gone, a second chance for
    one office comes out of the first chance of offices still waiting."""

    def test_retry_is_skipped_once_the_run_budget_is_spent(self):
        # The office STARTS inside the budget (the loop's own check let it
        # through) and the budget runs out during the attempt — so only the
        # retry is refused, not the office.
        def _slow_boom(_clock):
            time.sleep(0.15)
            raise RuntimeError("Page.goto: Timeout 30000ms exceeded")

        with mock.patch.object(R, "RUN_BUDGET_S", 0.05):
            h = _Harness("evening", ["19833"], {"19833": [_slow_boom, _ok]}).go()
        self.assertEqual(h.calls, [("19833", 0)], "no retry on a spent budget")
        self.assertEqual(h.finish["failed"], ["19833"])

    def test_retry_still_happens_with_budget_left(self):
        with mock.patch.object(R, "RUN_BUDGET_S", 20 * 60):
            h = _Harness("evening", ["19833"], {"19833": [_boom, _ok]}).go()
        self.assertEqual(len(h.calls), 2)
        self.assertEqual(h.finish["failed"], [])
