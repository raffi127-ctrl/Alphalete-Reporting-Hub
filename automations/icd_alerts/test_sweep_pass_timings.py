"""A slow sweep says WHERE it went, not just that it was slow.

2026-09-24: Cyrus's read was reported as "this read took 208 seconds" and
nothing else. Working out that it was one retried report pass -- rather than
his machine, his network or his data -- had to be done from arithmetic
(GRID_TIMEOUT_MS is 90s, a baseline read is ~60s, and every slow sweep across
the whole fleet lands in 181-244s), because the office laptops cannot be
reached to read their own logs.

Inference is not measurement. These pin that the breakdown reaches us with
the fault, so the next question -- is GRID_TIMEOUT_MS the thing to lower, and
to what -- is answered from numbers.

The instrumentation must never be able to cost a read: it is best-effort
everywhere, and a sweep with no timings reports exactly as it did before.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.shared import saraplus as S
from automations.icd_alerts import watchdog as W


class TheBreakdown(unittest.TestCase):

    def setUp(self):
        S.reset_pass_timings()

    def tearDown(self):
        S.reset_pass_timings()

    def test_a_clean_read_names_each_pass(self):
        S._record_pass("Internet", 1, 41, True)
        S._record_pass("AT&T", 1, 38, True)
        S._record_pass("All", 1, 35, True)
        self.assertEqual(S.pass_timings_summary(),
                         "Internet 41s | AT&T 38s | All 35s")

    def test_a_retried_pass_is_the_thing_it_points_at(self):
        """The shape the arithmetic predicted, made visible."""
        S._record_pass("Internet", 1, 41, True)
        S._record_pass("AT&T", 1, 91, False, "TimeoutError")
        S._record_pass("AT&T", 2, 41, True)
        S._record_pass("All", 1, 35, True)
        out = S.pass_timings_summary()
        self.assertIn("AT&T 132s", out, out)
        self.assertIn("attempt 1 failed 91s TimeoutError", out, out)

    def test_nothing_recorded_is_an_empty_string(self):
        """So a caller can append it unconditionally."""
        self.assertEqual(S.pass_timings_summary(), "")

    def test_a_reset_starts_the_next_read_clean(self):
        S._record_pass("Internet", 1, 41, True)
        S.reset_pass_timings()
        self.assertEqual(S.pass_timings_summary(), "")

    def test_it_cannot_grow_without_bound(self):
        for i in range(S._PASS_TIMINGS_CAP * 3):
            S._record_pass("Internet", 1, 1, True)
        self.assertLessEqual(len(S.pass_timings()), S._PASS_TIMINGS_CAP)

    def test_recording_never_raises(self):
        S._record_pass(None, "x", "not-a-number", True)   # nonsense on purpose
        S.pass_timings_summary()


class TheSlowFaultCarriesIt(unittest.TestCase):

    def setUp(self):
        S.reset_pass_timings()

    def tearDown(self):
        S.reset_pass_timings()

    def _report_for(self, fn):
        said = {}

        def report(stage, exc, office_key=""):
            said["stage"] = stage
            said["text"] = str(exc)

        with mock.patch.object(W, "SLOW_SECONDS", 0):
            W.timed("sweep", fn, log=lambda *_: None, report=report,
                    office_key="cyrus")
        return said

    def test_the_fault_says_where_the_time_went(self):
        S._record_pass("Internet", 1, 41, True)
        S._record_pass("AT&T", 1, 91, False, "TimeoutError")
        S._record_pass("AT&T", 2, 41, True)
        said = self._report_for(lambda: {"records": {}, "sales": {}})
        self.assertEqual(said["stage"], "sweep-slow")
        self.assertIn("Where it went:", said["text"])
        self.assertIn("attempt 1 failed 91s TimeoutError", said["text"])

    def test_the_original_sentence_is_still_there(self):
        S._record_pass("Internet", 1, 41, True)
        said = self._report_for(lambda: "ok")
        self.assertIn("Healthy is a few", said["text"])

    def test_a_sweep_with_no_timings_reports_exactly_as_before(self):
        said = self._report_for(lambda: "ok")
        self.assertIn("Healthy is a few", said["text"])
        self.assertNotIn("Where it went", said["text"],
                         "an empty breakdown should add nothing at all")

    def test_a_broken_breakdown_does_not_cost_the_fault(self):
        with mock.patch.object(S, "pass_timings_summary",
                               side_effect=RuntimeError("boom")):
            said = self._report_for(lambda: "ok")
        self.assertEqual(said["stage"], "sweep-slow",
                         "the fault was lost because its breakdown failed")


class TheReadResetsItsOwnTimings(unittest.TestCase):
    """Otherwise a fast read inherits the previous slow one's breakdown and
    the fault points at the wrong pass."""

    def test_read_day_resets_before_it_reads(self):
        import inspect
        from automations.icd_alerts import sara_read
        src = inspect.getsource(sara_read.read_day)
        self.assertIn("reset_pass_timings", src)
        self.assertLess(src.index("reset_pass_timings"),
                        src.index("sync_playwright() as p"),
                        "the reset has to happen before the passes run")


if __name__ == "__main__":
    unittest.main()
