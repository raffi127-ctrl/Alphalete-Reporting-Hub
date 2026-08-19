"""Arg-parsing safety tests for mini_control's `--enqueue` passthrough.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_mini_control

The report these guard is `resume_pushing` (office-11580 resume extract →
send-to-AI), whose live run is IRREVERSIBLE. The documented safe probe
`lucy rerun resume_pushing --dry-run` becomes `mini_control.py --by Megan
--enqueue rerun resume_pushing --dry-run`. If `--dry-run` were bound to
mini_control's own poll-side flag instead of passed through to the report, the
enqueued action would drop `--dry-run` and the mini would run it LIVE. These
tests pin the passthrough so that regression can't come back silently.
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator import mini_control


class _Recorder:
    """Stand-in for mini_control.enqueue that captures what main() would queue,
    so no Google Sheet is touched."""

    def __init__(self):
        self.calls = []

    def __call__(self, action, args="", by="Eve", *, sandbox=False, machine=None):
        self.calls.append(
            {"action": action, "args": args, "by": by,
             "sandbox": sandbox, "machine": machine})

    @property
    def last(self):
        return self.calls[-1]


class EnqueuePassthroughTest(unittest.TestCase):
    def setUp(self):
        self._real_enqueue = mini_control.enqueue
        self.rec = _Recorder()
        mini_control.enqueue = self.rec

    def tearDown(self):
        mini_control.enqueue = self._real_enqueue

    def _run(self, argv):
        rc = mini_control.main(argv)
        self.assertEqual(rc, 0)
        return self.rec.last

    def test_lucy_style_dry_run_passes_through(self):
        # Exactly what `lucy rerun resume_pushing --dry-run` expands to when the
        # runner is Lucy 2 (control flags interleaved around the action).
        call = self._run(
            ["--by", "Megan", "--machine", "Lucy 2",
             "--enqueue", "rerun", "resume_pushing", "--dry-run"])
        self.assertEqual(call["action"], "rerun")
        # The enqueued action string is what _action_rerun re-parses on the mini;
        # it MUST still carry --dry-run or the report runs LIVE.
        self.assertIn("--dry-run", call["args"])
        self.assertIn("resume_pushing", call["args"])
        # Control flags routed mini_control itself, not the report.
        self.assertEqual(call["machine"], "Lucy 2")
        self.assertEqual(call["by"], "Megan")

    def test_dry_run_passes_through_without_machine(self):
        call = self._run(
            ["--by", "Megan", "--enqueue", "rerun", "resume_pushing", "--dry-run"])
        self.assertEqual(call["action"], "rerun")
        self.assertIn("--dry-run", call["args"])
        self.assertIsNone(call["machine"])

    def test_other_report_flags_pass_through(self):
        # Non-colliding report flags were already fine; pin them so the fix
        # doesn't regress the common rescope case.
        call = self._run(
            ["--by", "Megan", "--enqueue", "rerun", "daily_metrics", "--only", "churn"])
        self.assertEqual(call["action"], "rerun")
        self.assertEqual(call["args"], "daily_metrics --only churn")

    def test_control_flag_after_action_still_routes(self):
        # A trailing --machine steers mini_control (hoisted out) and must NOT leak
        # into the report's args.
        call = self._run(
            ["--enqueue", "rerun", "resume_pushing", "--machine", "Lucy 2"])
        self.assertEqual(call["machine"], "Lucy 2")
        self.assertNotIn("--machine", call["args"])
        self.assertEqual(call["args"], "resume_pushing")


class HoistControlFlagsTest(unittest.TestCase):
    def test_hoists_value_and_bool_flags_to_front(self):
        out = mini_control._hoist_control_flags(
            ["--enqueue", "rerun", "X", "--machine", "Lucy 2", "--sandbox"])
        # Control flags moved ahead of --enqueue so REMAINDER can't swallow them.
        self.assertEqual(out[:3], ["--machine", "Lucy 2", "--sandbox"])
        self.assertEqual(out[3:], ["--enqueue", "rerun", "X"])

    def test_leaves_report_flags_in_place(self):
        out = mini_control._hoist_control_flags(
            ["--enqueue", "rerun", "X", "--dry-run", "--only", "churn"])
        # --dry-run/--only are report flags, not control flags — untouched.
        self.assertEqual(
            out, ["--enqueue", "rerun", "X", "--dry-run", "--only", "churn"])


class TheRestartHold(unittest.TestCase):
    """`restart_poller` schedules a kill ~3s out and returns, so the rows behind
    it used to run on the code this process booted with — the reason a deploy's
    third row (update, restart_poller, <the thing>) silently ran on the OLD
    code, and why an incident close failed two seconds after a restart on
    2026-08-19."""

    def setUp(self):
        self._saved = mini_control._restart_scheduled_at

    def tearDown(self):
        mini_control._restart_scheduled_at = self._saved

    def test_no_restart_no_hold(self):
        mini_control._restart_scheduled_at = None
        self.assertFalse(mini_control._restart_hold_active())

    def test_a_scheduled_restart_holds_the_queue(self):
        import time
        mini_control._restart_scheduled_at = time.time()
        self.assertTrue(mini_control._restart_hold_active())

    def test_a_kickstart_that_never_landed_releases_the_queue(self):
        """Time-boxed on purpose: a hold that outlives a failed restart would
        freeze the one channel used to unstick the machine."""
        import time
        mini_control._restart_scheduled_at = (
            time.time() - mini_control._RESTART_HOLD_SECS - 1)
        self.assertFalse(mini_control._restart_hold_active())


if __name__ == "__main__":
    unittest.main()
