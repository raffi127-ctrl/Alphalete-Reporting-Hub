"""Canceling a RUNNING queue row stops the run, so the rows behind it can go.

WHY THIS EXISTS (Megan 2026-10-19). `rerun ad_photo_threads --office cody` was
set to 'canceled' on Lucy 1 a few minutes after it started at 15:33. The label
changed and nothing else did: it ran on to its 75-minute timeout and seven rows
waited behind it. These pin the fix: the run checks its own row, a cancel stops
the run AND what it launched, a Sheet hiccup never stops anything, and the row
ends 'canceled', not 'failed'.

    python -m unittest automations.day_orchestrator.test_mini_control_cancel_running

Nothing here touches a Sheet, Slack or the Hub: the worksheet is a fake and the
only real processes are short python sleeps started by the test itself.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import mini_control as mc


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunCmdStopsOnCancel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pidfile = Path(self.tmp.name) / "grandchild.pid"
        p = mock.patch.object(mc, "_CANCEL_POLL_S", 0.2)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _parent_with_grandchild(self):
        # The report stands in for a browser report: it starts a child of its
        # own (Chrome, in real life) and then works for a minute.
        code = (
            "import subprocess, sys, time\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(self.pidfile)!r}, 'w').write(str(g.pid))\n"
            "print('working', flush=True)\n"
            "time.sleep(60)\n")
        return [sys.executable, "-c", code]

    def test_a_cancel_stops_the_run_within_seconds(self):
        calls = []

        def should_stop():
            calls.append(1)
            return len(calls) >= 3            # the person cancels ~0.6s in

        t0 = time.monotonic()
        ok, result = mc._run_cmd(self._parent_with_grandchild(), timeout_s=60,
                                 should_stop=should_stop)
        self.assertFalse(ok)
        self.assertTrue(result.startswith(mc.CANCELED_PREFIX), result)
        self.assertLess(time.monotonic() - t0, 30,
                        "the run should stop at the cancel, not its timeout")

    @unittest.skipIf(os.name == "nt", "process check below is POSIX-only")
    def test_a_cancel_also_stops_what_the_run_launched(self):
        # A Chrome left behind holds the shared profile and stalls the NEXT row.
        def should_stop():
            return self.pidfile.exists()

        mc._run_cmd(self._parent_with_grandchild(), timeout_s=60,
                    should_stop=should_stop)
        gpid = int(self.pidfile.read_text())
        for _ in range(50):                   # give the OS a moment to reap it
            if not _alive(gpid):
                break
            time.sleep(0.1)
        self.assertFalse(_alive(gpid), "the report's own child was left running")

    def test_no_cancel_runs_to_the_end_as_before(self):
        ok, result = mc._run_cmd([sys.executable, "-c", "print('hello')"],
                                 timeout_s=30, should_stop=lambda: False)
        self.assertTrue(ok)
        self.assertIn("exit 0", result)
        self.assertIn("hello", result)

    def test_a_broken_check_never_stops_a_run(self):
        def should_stop():
            raise RuntimeError("Sheets 503")

        ok, result = mc._run_cmd(
            [sys.executable, "-c", "import time; time.sleep(0.6); print('done')"],
            timeout_s=30, should_stop=should_stop)
        self.assertTrue(ok, result)

    def test_without_a_check_nothing_changes(self):
        ok, result = mc._run_cmd([sys.executable, "-c", "print('x')"], timeout_s=30)
        self.assertTrue(ok)

    def test_the_timeout_still_applies(self):
        ok, result = mc._run_cmd(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_s=1, should_stop=lambda: False)
        self.assertFalse(ok)
        self.assertTrue(result.startswith("timed out"), result)


class CurrentRowCanceled(unittest.TestCase):

    class _WS:
        def __init__(self, status=None, boom=False):
            self.status, self.boom = status, boom

        def cell(self, row, col):
            if self.boom:
                raise ConnectionError("network blinked")
            assert col == 5, "Status is column E"
            return mock.Mock(value=self.status)

    def _ask(self, ws):
        with mock.patch.object(mc, "_CURRENT_ROW", (ws, 7) if ws else None):
            return mc._current_row_canceled()

    def test_canceled_reads_true(self):
        self.assertTrue(self._ask(self._WS("canceled")))
        self.assertTrue(self._ask(self._WS(" Cancelled ")))

    def test_running_reads_false(self):
        self.assertFalse(self._ask(self._WS("running")))

    def test_a_read_error_fails_open(self):
        self.assertFalse(self._ask(self._WS(boom=True)))

    def test_no_current_row_reads_false(self):
        self.assertFalse(self._ask(None))


class PollOnceKeepsTheCanceledStatus(unittest.TestCase):

    def _run(self, handler):
        sheet = [{"Queued At": "", "Action": "rerun", "Args": "x", "By": "Eve",
                  "Status": "queued", "Result": "", "Finished At": ""}]
        seen = {}

        class _WS:
            def get_all_records(self):
                return [dict(r) for r in sheet]

        def _set(_ws, rownum, status, result="", **_k):
            sheet[rownum - 2]["Status"] = status
            sheet[rownum - 2]["Result"] = result

        def wrapped(args):
            seen["row_during"] = mc._CURRENT_ROW
            return handler(args)

        with mock.patch.object(mc, "_open", lambda *a, **k: _WS()), \
             mock.patch.object(mc, "_set", _set), \
             mock.patch.object(mc, "ACTIONS", {"rerun": wrapped}), \
             mock.patch.object(mc, "_reclaim_orphans", lambda *a, **k: 0), \
             mock.patch.object(mc, "_restart_hold_active", lambda: False), \
             mock.patch.object(mc, "_plumbing_waiting", lambda *a, **k: False), \
             mock.patch.object(mc, "_daily_cap", lambda: 999):
            mc.poll_once(lane="main")
        return sheet[0], seen

    def test_a_stopped_run_ends_canceled_not_failed(self):
        row, _ = self._run(lambda a: (False, mc.CANCELED_PREFIX + " at 16:40"))
        self.assertEqual(row["Status"], "canceled")

    def test_an_ordinary_failure_is_still_failed(self):
        row, _ = self._run(lambda a: (False, "exit 1"))
        self.assertEqual(row["Status"], "failed")

    def test_the_handler_can_see_its_row_and_it_is_cleared_after(self):
        _, seen = self._run(lambda a: (True, "exit 0"))
        self.assertIsNotNone(seen["row_during"])
        self.assertEqual(seen["row_during"][1], 2)   # first data row
        self.assertIsNone(mc._CURRENT_ROW)


class CanceledRerunStaysOutOfTheIncidentChannel(unittest.TestCase):
    """A person stopped it: that says nothing about the report, so no
    'closed a run with status FAILED' post and no cleared failure."""

    def test_publish_gets_the_quiet_flag(self):
        report = mock.Mock(command=["automations.x.run"], base_args=[],
                           source_type="sheet", timeout_minutes=1,
                           display_name="X", duplicate_guard=False)
        cfg = mock.Mock(raw={"reports": {"x": {}}})
        published = {}

        def fake_done(report_id, name, ok, run_id, probe, manual=False):
            published["probe"] = probe

        with mock.patch.object(mc.registry, "load_config", lambda: cfg), \
             mock.patch.object(mc.registry, "resolve_report", lambda c, n: report), \
             mock.patch.object(mc, "_run_cmd",
                               lambda *a, **k: (False, mc.CANCELED_PREFIX + " at 16:40")), \
             mock.patch.object(mc, "_publish_rerun_done", fake_done), \
             mock.patch("automations.day_orchestrator.hub_publish.publish_running",
                        lambda *a, **k: None):
            ok, result = mc._action_rerun("x")
        self.assertFalse(ok)
        self.assertEqual(published["probe"], "canceled")
        self.assertNotIn("probe run", result)


if __name__ == "__main__":
    unittest.main()
