"""A sweep that hangs must give up, and every sweep must say how long it took.

Megan, 2026-09-18: "I want the ICDs to enroll and then be 100% hands off."

Roshan's brand-new iMac went quiet twice in one day -- 50 minutes, then 20 --
while every other office checked in every two minutes. It reports
never_sleeps, it is on power, and it raised NO fault either time. My first
answer was her wifi and it was wrong.

The job fires every two minutes and launchd will not start a second copy
while one is running, so a sweep that takes twenty minutes produces exactly
what was seen: a twenty-minute hole, no errors, then everything at once --
which the office experiences as "she's super delay today". Nothing anywhere
recorded how long a run took, so two outages passed with no evidence either
way.
"""
from __future__ import annotations

import threading
import time
import unittest

from automations.icd_alerts import watchdog as W


class EverySweepSaysHowLongItTookTest(unittest.TestCase):
    def test_a_fast_run_is_timed(self):
        said = []
        W.timed("sweep", lambda: "ok", log=said.append)
        self.assertTrue(any("took" in m for m in said))

    def test_the_value_is_returned_unchanged(self):
        self.assertEqual(W.timed("sweep", lambda: {"records": 3}, log=lambda *_: None),
                         {"records": 3})

    def test_a_fast_run_reports_nothing(self):
        """A healthy sweep must not file a fault; noise is how a real one gets
        ignored."""
        filed = []
        W.timed("sweep", lambda: "ok", log=lambda *_: None,
                report=lambda s, e, office_key="": filed.append(s))
        self.assertEqual(filed, [])


class AHangIsAbandonedTest(unittest.TestCase):
    def test_it_raises_rather_than_running_forever(self):
        with self.assertRaises(W.SweepTimeout):
            W.timed("sweep", lambda: time.sleep(4), log=lambda *_: None,
                    seconds=1)

    def test_it_reports_itself_with_the_reason(self):
        filed = []
        with self.assertRaises(W.SweepTimeout):
            W.timed("sweep", lambda: time.sleep(4), log=lambda *_: None,
                    report=lambda s, e, office_key="": filed.append((s, str(e))),
                    seconds=1)
        self.assertEqual(filed[0][0], "sweep-timeout")
        self.assertIn("abandoned", filed[0][1])
        # It must say nothing is lost, or an office reads this as missing data.
        self.assertIn("Nothing is lost", filed[0][1])

    def test_the_office_key_travels(self):
        """A machine can hold two campaigns; an unlabelled fault lands on
        whichever enrolled first."""
        filed = []
        with self.assertRaises(W.SweepTimeout):
            W.timed("box", lambda: time.sleep(4), log=lambda *_: None,
                    report=lambda s, e, office_key="": filed.append(office_key),
                    seconds=1, office_key="roshan")
        self.assertEqual(filed, ["roshan"])

    def test_a_failed_report_does_not_mask_the_timeout(self):
        with self.assertRaises(W.SweepTimeout):
            W.timed("sweep", lambda: time.sleep(4), log=lambda *_: None,
                    report=lambda *_a, **_k: 1 / 0, seconds=1)


class ARealFailureStillSurfacesTest(unittest.TestCase):
    def test_the_original_error_is_not_swallowed(self):
        class Boom(RuntimeError):
            pass
        with self.assertRaises(Boom):
            W.timed("sweep", lambda: (_ for _ in ()).throw(Boom("real")),
                    log=lambda *_: None)

    def test_it_is_still_timed(self):
        said = []
        with self.assertRaises(ValueError):
            W.timed("sweep", lambda: (_ for _ in ()).throw(ValueError("x")),
                    log=said.append)
        self.assertTrue(any("took" in m for m in said))


class TheThresholdsAreSaneTest(unittest.TestCase):
    def test_the_deadline_is_longer_than_slow(self):
        self.assertGreater(W.DEADLINE_SECONDS, W.SLOW_SECONDS)

    def test_the_deadline_spans_more_than_one_tick(self):
        """Two minutes is the tick. Cutting a sweep off at one would kill
        healthy reads on the slowest office."""
        self.assertGreaterEqual(W.DEADLINE_SECONDS, 240)


class TheWholeRunHasAHardCeilingTest(unittest.TestCase):
    """Kash's iMac, 2026-10-02: a run hung past every stage deadline and never
    exited, so launchd never started another -- three dark days, no fault."""

    def setUp(self):
        self._kill = W._kill_descendants
        W._kill_descendants = lambda: None   # never SIGKILL the test runner's kids

    def tearDown(self):
        W._kill_descendants = self._kill

    def test_a_stuck_run_reports_then_exits(self):
        filed, exited = [], threading.Event()
        W.arm_hard_ceiling(0.05, log=lambda *_: None,
                           report=lambda s, e: filed.append(s),
                           _exit=lambda code: exited.set())
        self.assertTrue(exited.wait(5))
        self.assertEqual(filed, ["run-timeout"])

    def test_a_hung_report_does_not_keep_it_alive(self):
        """The relay can hang too; the exit must still come."""
        exited = threading.Event()
        orig = threading.Thread.join
        threading.Thread.join = lambda self, timeout=None: None  # skip the 30s
        try:
            W.arm_hard_ceiling(0.05, log=lambda *_: None,
                               report=lambda s, e: time.sleep(60),
                               _exit=lambda code: exited.set())
            self.assertTrue(exited.wait(5))
        finally:
            threading.Thread.join = orig

    def test_a_run_that_finishes_never_trips_it(self):
        exited = threading.Event()
        t = W.arm_hard_ceiling(60, log=lambda *_: None,
                               _exit=lambda code: exited.set())
        t.cancel()
        self.assertFalse(exited.wait(0.2))

    def test_the_ceiling_outlasts_every_stage(self):
        self.assertGreater(W.HARD_CEILING_SECONDS, 3 * W.DEADLINE_SECONDS)


if __name__ == "__main__":
    unittest.main()
