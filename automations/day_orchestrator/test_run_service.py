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
from dataclasses import asdict

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


class FailureAlertTest(unittest.TestCase):
    """The immediate per-report failure email (`_alert_new_failures` /
    `_maybe_failure_alert`). Megan 2026-07-20 wanted a heads-up the MOMENT a report
    fails — before the 7:30 checkpoint / final summary — so it can be fixed while
    the batch is still running rather than found hours later. These pin: FAILED
    always alerts; INCOMPLETE alerts only once it can't self-heal (so a transient
    partial that the retry/service-tick fixes doesn't cry wolf); each report alerts
    at most once a day."""

    def setUp(self):
        self.sent = []
        from automations.day_orchestrator import notify
        self._notify = notify
        self._real_send = notify.send_failure_alert
        self._real_retryable = R._retryable_incomplete
        notify.send_failure_alert = lambda cfg, ds, rs, **kw: self.sent.append(rs.report_id)
        # Retryability is controlled per-test via self.retryable (report_ids that
        # can still self-heal) so these don't reach the manifest/registry.
        self.retryable = set()
        R._retryable_incomplete = lambda rs, r: rs.report_id in self.retryable

    def tearDown(self):
        self._notify.send_failure_alert = self._real_send
        R._retryable_incomplete = self._real_retryable

    def _ds(self, **statuses):
        ds = state.DayState(date="2026-07-20")
        for rid, st in statuses.items():
            ds.reports[rid] = state.ReportState(report_id=rid, status=st)
        return ds

    def _sweep(self, ds):
        R._alert_new_failures(cfg=None, ds=ds,
                              todays_by_id={rid: _Report(rid) for rid in ds.reports},
                              channel="email", dry_run=True)

    def test_failed_report_alerts_once(self):
        ds = self._ds(a=state.FAILED)
        self._sweep(ds)
        self._sweep(ds)                       # second pass must not re-email
        self.assertEqual(self.sent, ["a"])
        self.assertEqual(ds.failure_alerts_sent, ["a"])

    def test_unrecoverable_incomplete_alerts(self):
        ds = self._ds(a=state.INCOMPLETE)     # not in self.retryable → stuck
        self._sweep(ds)
        self.assertEqual(self.sent, ["a"])

    def test_retryable_incomplete_stays_quiet(self):
        ds = self._ds(a=state.INCOMPLETE)
        self.retryable = {"a"}                # can still self-heal → no alert yet
        self._sweep(ds)
        self.assertEqual(self.sent, [])
        # …and once it exhausts its retries, the next sweep DOES alert.
        self.retryable = set()
        self._sweep(ds)
        self.assertEqual(self.sent, ["a"])

    def test_healthy_states_never_alert(self):
        ds = self._ds(a=state.DONE, b=state.PENDING, c=state.STILL_TRYING,
                      d=state.SKIPPED)
        self._sweep(ds)
        self.assertEqual(self.sent, [])

    def test_send_failure_that_raises_does_not_crash_the_batch(self):
        def boom(cfg, ds, rs, **kw):
            raise RuntimeError("smtp down")
        self._notify.send_failure_alert = boom
        ds = self._ds(a=state.FAILED)
        self._sweep(ds)                       # must not raise
        # still marked sent, so a flapping SMTP can't turn into an email storm
        self.assertEqual(ds.failure_alerts_sent, ["a"])


class BackstopNothingToDoTest(unittest.TestCase):
    """The noon backstop's two flavours of "not ready" (Eve 2026-07-31).

    sci_campaigns waits all morning for Adriana's tracker email; its probe
    deliberately reports NOT-ready when the tab is already current, so the
    orchestrator keeps circling back in case the mail lands at 5pm. The backstop
    then retired that as MISSED_NOT_READY, which closed its Hub pill red and fired
    a #claudecorrections fix-block — every Friday she sent late, for a report doing
    exactly what it was built to do. A probe that says "nothing to do" now retires
    SKIPPED (quiet); one that says "data never landed" still MISSES (alerts)."""

    def _waiting(self, **kw):
        ds = state.DayState(date="2026-07-31")
        for rid, nothing_to_do in kw.items():
            ds.reports[rid] = state.ReportState(report_id=rid)
            ds.set(rid, state.STILL_TRYING, reason=f"{rid} reason",
                   waiting_on=f"{rid} reason", nothing_to_do=nothing_to_do)
        return ds

    def test_nothing_to_do_is_skipped_not_missed(self):
        ds = self._waiting(sci_campaigns=True, some_tableau=False)
        R._apply_backstop(ds, 20)
        self.assertEqual(ds.reports["sci_campaigns"].status, state.SKIPPED)
        self.assertIn("nothing to do", ds.reports["sci_campaigns"].last_reason)
        # a report genuinely still waiting on data is untouched by this
        self.assertEqual(ds.reports["some_tableau"].status, state.MISSED_NOT_READY)

    def test_a_stale_session_still_wins(self):
        ds = self._waiting(x=True)
        ds.set("x", state.STILL_TRYING, reason="ownerville session stale",
               waiting_on="ownerville session stale", nothing_to_do=True)
        R._apply_backstop(ds, 20)
        self.assertEqual(ds.reports["x"].status, state.BLOCKED_SESSION)

    def test_state_file_survives_the_new_field(self):
        """Old day_state JSON (written before the field existed) still loads."""
        rs = state.ReportState(report_id="a")
        raw = {k: v for k, v in asdict(rs).items() if k != "nothing_to_do"}
        self.assertFalse(state.ReportState(**raw).nothing_to_do)


class ManifestIdTest(unittest.TestCase):
    """The auto-retry gate must find the manifest by the report's CARD id.

    2026-08-17: daily_rep_breakdown dropped Phase 2 and went straight to a manual
    alert — no retry logged — even though the whole-phase auto-retry (2026-08-10)
    was written for exactly that case. Cause: the manifest is filed under the
    verify block's `report_id` ('daily-rep-breakdown'), the gate looked it up
    under the scheduler key ('daily_rep_breakdown'), and 23 of the 40
    manifest-verified reports have ids that differ that way — so for all of them
    BOTH auto-retries silently found nothing to do."""

    CARD = "daily-rep-breakdown"
    KEY = "daily_rep_breakdown"

    def setUp(self):
        import tempfile
        from pathlib import Path
        from automations.shared import run_manifest as rm
        self._rm, self._real_dir = rm, rm.MANIFEST_DIR
        self._tmp = tempfile.TemporaryDirectory()
        rm.MANIFEST_DIR = Path(self._tmp.name)

    def tearDown(self):
        self._rm.MANIFEST_DIR = self._real_dir
        self._tmp.cleanup()

    def _report(self, card_id):
        r = _Report(self.KEY)
        r.verify = {"type": "manifest", "report_id": card_id}
        return r

    def _incomplete(self):
        rs = state.ReportState(report_id=self.KEY)
        rs.status = state.INCOMPLETE
        return rs

    def _write_phase_fail(self, report_id):
        self._rm.write_manifest(report_id, failed=["Phase 2 — ownerville scrape"],
                                retry_args=[], kind="phase", ok=False,
                                run_ts=dt.datetime(2026, 8, 17, 4, 0))

    def test_phase_drop_under_a_hyphenated_card_id_is_retryable(self):
        self._write_phase_fail(self.CARD)
        self.assertTrue(R._retryable_incomplete(self._incomplete(),
                                                self._report(self.CARD)))

    def test_the_scheduler_key_alone_no_longer_decides(self):
        """The regression itself: manifest filed under the card id, gate asked
        for the scheduler key, answer was 'nothing to retry'."""
        self._write_phase_fail(self.CARD)
        self.assertIsNone(self._rm.retry_whole_spec(self.KEY))
        self.assertEqual(R._manifest_id(self._incomplete(),
                                        self._report(self.CARD)), self.CARD)

    def test_a_matching_id_still_works(self):
        """The 17 reports whose two ids agree must behave exactly as before."""
        self._write_phase_fail(self.KEY)
        r = self._report(self.KEY)
        self.assertTrue(R._retryable_incomplete(self._incomplete(), r))

    def test_no_verify_report_id_falls_back_to_the_key(self):
        r = _Report(self.KEY)
        r.verify = {"type": "manifest"}
        self.assertEqual(R._manifest_id(self._incomplete(), r), self.KEY)

    def test_a_clean_manifest_is_not_retryable(self):
        self._rm.mark_clean(self.CARD, kind="phase")
        self.assertFalse(R._retryable_incomplete(self._incomplete(),
                                                 self._report(self.CARD)))

    def test_the_cap_still_holds(self):
        self._write_phase_fail(self.CARD)
        rs = self._incomplete()
        rs.auto_retries = R.MAX_AUTO_RETRIES
        self.assertFalse(R._retryable_incomplete(rs, self._report(self.CARD)))


if __name__ == "__main__":
    unittest.main()
