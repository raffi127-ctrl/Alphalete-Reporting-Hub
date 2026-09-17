"""Closing out yesterday from the office's own machine.

THE POINT OF THE PASS: the metrics thread's knocks board should be the
FINISHED day, read by the office's own machine, not whatever its last
in-window sweep happened to catch. These pin the decisions that make that
safe -- when it runs, when it must not, and that it never costs the machine
its real work.

    python -m unittest automations.icd_alerts.test_closeout
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from automations.icd_alerts import closeout as CO

MON = dt.date(2026, 9, 14)
TUE = dt.date(2026, 9, 15)
WED = dt.date(2026, 9, 16)
SAT = dt.date(2026, 9, 12)
SUN = dt.date(2026, 9, 13)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._saved = CO.STATE
        CO.STATE = Path(self._dir.name) / "closeout.json"

    def tearDown(self):
        CO.STATE = self._saved
        self._dir.cleanup()


class WhichDay(_Tmp):
    def test_it_closes_out_the_day_before(self):
        self.assertEqual(CO.due(WED), TUE)

    def test_monday_closes_out_nothing(self):
        """Sunday is not a selling day anywhere in the org. Reading it would
        relay a blank row and have it read as a quiet day."""
        self.assertIsNone(CO.previous_selling_day(MON))
        self.assertIsNone(CO.due(MON))

    def test_sunday_still_closes_out_saturday(self):
        """Saturday IS a selling day, and its board is nobody's Sunday job."""
        self.assertEqual(CO.due(SUN), SAT)


class RunsOnce(_Tmp):
    def test_a_finished_day_is_not_read_again(self):
        calls = []
        CO.maybe_run(lambda d: calls.append(d) or 0, today=WED,
                     log=lambda *a: None)
        CO.maybe_run(lambda d: calls.append(d) or 0, today=WED,
                     log=lambda *a: None)
        self.assertEqual(calls, [TUE], "closed out the same day twice")

    def test_a_failed_read_is_retried(self):
        calls = []
        CO.maybe_run(lambda d: calls.append(d) or 1, today=WED,
                     log=lambda *a: None)
        CO.maybe_run(lambda d: calls.append(d) or 1, today=WED,
                     log=lambda *a: None)
        self.assertEqual(calls, [TUE, TUE])

    def test_it_gives_up_rather_than_failing_all_night(self):
        """The job wakes every few minutes. An office whose OwnerVille login
        has expired would otherwise spend the night generating fault reports
        with somebody's name on them."""
        calls = []
        for _ in range(CO.MAX_ATTEMPTS + 4):
            CO.maybe_run(lambda d: calls.append(d) or 1, today=WED,
                         log=lambda *a: None)
        self.assertEqual(len(calls), CO.MAX_ATTEMPTS)
        self.assertIsNone(CO.due(WED))

    def test_a_raising_read_is_caught_and_retried(self):
        def _boom(day):
            raise RuntimeError("ownerville said no")

        got = CO.maybe_run(_boom, today=WED, log=lambda *a: None)
        self.assertIsNone(got, "a failed close-out must not report success")
        self.assertEqual(CO.due(WED), TUE, "and must stay owed")

    def test_success_is_reported_as_the_day_closed(self):
        self.assertEqual(
            CO.maybe_run(lambda d: 0, today=WED, log=lambda *a: None), TUE)


class State(_Tmp):
    def test_an_unreadable_state_file_is_treated_as_fresh(self):
        CO.STATE.parent.mkdir(parents=True, exist_ok=True)
        CO.STATE.write_text("{not json")
        self.assertEqual(CO.due(WED), TUE)

    def test_old_days_are_pruned(self):
        CO.maybe_run(lambda d: 0, today=WED, log=lambda *a: None)
        held = json.loads(CO.STATE.read_text())
        held["2020-01-01"] = {"done": True}
        CO.STATE.write_text(json.dumps(held))
        CO.maybe_run(lambda d: 0, today=dt.date(2026, 9, 18),
                     log=lambda *a: None)
        self.assertNotIn("2020-01-01", json.loads(CO.STATE.read_text()))


class RunsAheadOfTheGate(unittest.TestCase):
    """It has to run BEFORE the selling-window check, or it can never help.

    The agent's window opens at 10:00 local and the metrics thread reads the
    board at about 06:50 Central -- so a close-out that waits for the window
    is always too late to be the number anybody sees.
    """

    def test_the_hook_precedes_the_if_due_return(self):
        src = Path("automations/icd_alerts/run.py").read_text()
        hook = src.index("closeout.maybe_run")
        gate = src.index("if args.if_due and not C.in_selling_window():")
        self.assertLess(hook, gate,
                        "the close-out must run before the window gate")

    def test_the_window_really_does_open_after_the_metrics_thread_reads(self):
        """If this ever stops being true, the hook's placement stops mattering
        and the reasoning in closeout's docstring needs revisiting."""
        from automations.icd_alerts import config as C
        self.assertGreaterEqual(C.DAY_START_HHMM[0], 8)


if __name__ == "__main__":
    unittest.main()
