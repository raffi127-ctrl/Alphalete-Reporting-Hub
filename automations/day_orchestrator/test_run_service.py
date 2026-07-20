"""Tests for the pass loop's SERVICE TICK (`run._service_owed`).

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_run_service

WHAT THESE GUARD (2026-07-20). The orchestrator's recovery mechanisms used to be
coupled to the pass BOUNDARY — but a pass runs every ready report serially, so
its duration is the SUM of their runtimes. On 2026-07-20 pass 1 ran 04:00 ->
~07:47 and was the only pass of the day, so every "each pass" mechanism fired
exactly once. Two live reports were hurt:

  * tableau_screenshots flaked at 04:29:05 (a socket timeout dropped 5 of 7
    tracker images in #aeon-sales). Its "~90s" end-of-pass retry was queued for
    ~07:47 — 3h18m out. A human re-ran it by hand first.
  * tableau_screenshots_box probed not-ready at 04:31 and was never re-probed.
    Its extract landed ~07:42 but it only posted at 08:01, released by the 08:00
    fail-open floor rather than by the probe noticing.

`_service_owed` runs between REPORTS instead of between PASSES, so both recover
in minutes. Tests 1 and 4 are those two incidents replayed directly. The rest pin
the guards that keep the tick from becoming a new problem: it must respect the
run budget and the backoff, must not hammer Tableau with probes, must never touch
a report that isn't STILL_TRYING, and must never crash the pass it runs inside.

See "Later thoughts/orchestrator-single-long-pass.md".
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.day_orchestrator import run as R
from automations.day_orchestrator import state


class _Report:
    def __init__(self, report_id, source_type="tableau"):
        self.report_id = report_id
        self.source_type = source_type
        self.display_name = report_id


class _Cache:
    """Stand-in for ReadinessCache that counts probes, so the throttle is
    observable (a real probe is a Tableau query)."""

    def __init__(self, ready):
        self._ready = ready
        self.probes = 0

    def report_ready(self, rpt):
        self.probes += 1
        rd = type("RD", (), {})()
        rd.ready = self._ready
        rd.reason = "extract refreshed" if self._ready else "extract not refreshed"
        return rd


class _ExplodingCache:
    def report_ready(self, rpt):
        raise RuntimeError("tableau down")


class ServiceTickTest(unittest.TestCase):
    TARGET = dt.date(2026, 7, 20)

    def setUp(self):
        self.launched = []
        self._real_attempt = R._attempt_report
        self._real_guard = R._guard_chrome

        def fake_attempt(ds, r, rs, target, *, dry_run, simulate):
            self.launched.append(r.report_id)
            ds.set(r.report_id, state.DONE, reason="test run")
            return "done"

        R._attempt_report = fake_attempt
        R._guard_chrome = lambda r, **kw: None

    def tearDown(self):
        R._attempt_report = self._real_attempt
        R._guard_chrome = self._real_guard

    def _state(self, report_id, status, waiting_on, attempts=1, age_s=999):
        ds = state.DayState(date="2026-07-20")
        rs = state.ReportState(report_id=report_id, status=status,
                               attempts=attempts, waiting_on=waiting_on)
        rs.last_attempt_ts = ((dt.datetime.now() - dt.timedelta(seconds=age_s))
                              .replace(microsecond=0).isoformat())
        ds.reports[report_id] = rs
        return ds, rs

    def _tick(self, ds, rs, report_id, cache, probed_at=None, simulate=False):
        R._service_owed(ds, [(_Report(report_id), rs)], self.TARGET, cache,
                        probed_at if probed_at is not None else {},
                        dry_run=False, simulate=simulate)

    # ---- the two 2026-07-20 incidents, replayed ----

    def test_flaked_run_is_retried_mid_pass(self):
        """#aeon-sales: a flaked run recovers on the next tick, not at end of pass."""
        ds, rs = self._state("tableau_screenshots", state.STILL_TRYING,
                             R.FLAKE_WAITING_ON)
        self._tick(ds, rs, "tableau_screenshots", _Cache(False))
        self.assertEqual(self.launched, ["tableau_screenshots"])

    def test_gated_report_runs_the_moment_its_data_lands(self):
        """Box: re-probed on the clock, so it posts when the extract lands rather
        than waiting for the 08:00 fail-open floor."""
        ds, rs = self._state("tableau_screenshots_box", state.STILL_TRYING,
                             "extract not refreshed")
        cache = _Cache(True)
        self._tick(ds, rs, "tableau_screenshots_box", cache)
        self.assertEqual(self.launched, ["tableau_screenshots_box"])
        self.assertEqual(cache.probes, 1)

    # ---- guards ----

    def test_backoff_is_respected(self):
        ds, rs = self._state("x", state.STILL_TRYING, R.FLAKE_WAITING_ON, age_s=5)
        self._tick(ds, rs, "x", _Cache(False))
        self.assertEqual(self.launched, [])

    def test_run_budget_is_respected(self):
        ds, rs = self._state("x", state.STILL_TRYING, R.FLAKE_WAITING_ON,
                             attempts=R.MAX_RUN_RETRIES)
        self._tick(ds, rs, "x", _Cache(False))
        self.assertEqual(self.launched, [])

    def test_not_ready_report_is_left_waiting(self):
        ds, rs = self._state("x", state.STILL_TRYING, "extract not refreshed")
        self._tick(ds, rs, "x", _Cache(False))
        self.assertEqual(self.launched, [])

    def test_reprobe_is_throttled(self):
        """Many ticks per pass must not mean many Tableau probes."""
        ds, rs = self._state("x", state.STILL_TRYING, "extract not refreshed")
        cache, probed_at = _Cache(False), {}
        for _ in range(5):
            self._tick(ds, rs, "x", cache, probed_at)
        self.assertEqual(cache.probes, 1)

    def test_only_still_trying_reports_are_serviced(self):
        for status in (state.DONE, state.FAILED, state.PENDING,
                       state.INCOMPLETE, state.SKIPPED):
            with self.subTest(status=status):
                ds, rs = self._state("x", status, R.FLAKE_WAITING_ON)
                self._tick(ds, rs, "x", _Cache(True))
        self.assertEqual(self.launched, [])

    def test_simulate_never_probes(self):
        ds, rs = self._state("x", state.STILL_TRYING, "extract not refreshed")
        cache = _Cache(True)
        self._tick(ds, rs, "x", cache, simulate=True)
        self.assertEqual(cache.probes, 0)
        self.assertEqual(self.launched, [])

    def test_probe_failure_does_not_crash_the_pass(self):
        ds, rs = self._state("x", state.STILL_TRYING, "extract not refreshed")
        self._tick(ds, rs, "x", _ExplodingCache())   # must not raise
        self.assertEqual(self.launched, [])


if __name__ == "__main__":
    unittest.main()
