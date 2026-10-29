"""A scheduled enqueuer must not stack copies of a job that is already waiting.

2026-10-29: the new-start thread scan queued `rerun new_start_thread_replies`
every 30 min while Lucy 1's queue was stuck — five copies, four canceled by
hand. Nothing here touches Sheets or sends.

    python -m unittest automations.day_orchestrator.test_mini_control_skip_waiting
"""
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import mini_control as mc

HDR = ["Queued At", "Action", "Args", "By", "Status", "Result", "Finished At"]


def _ws(rows):
    w = mock.MagicMock()
    w.get_all_values.return_value = [HDR] + rows
    return w


def _row(action, args, status):
    return ["t", action, args, "Thread Scan", status, "", ""]


class AlreadyWaiting(unittest.TestCase):
    def test_a_queued_copy_counts(self):
        ws = _ws([_row("rerun", "new_start_thread_replies", "queued")])
        self.assertTrue(mc._already_waiting(ws, "rerun", "new_start_thread_replies"))

    def test_a_running_copy_counts(self):
        ws = _ws([_row("rerun", "new_start_thread_replies", "running")])
        self.assertTrue(mc._already_waiting(ws, "rerun", "new_start_thread_replies"))

    def test_finished_or_canceled_copies_do_not(self):
        ws = _ws([_row("rerun", "new_start_thread_replies", s)
                  for s in ("done", "failed", "canceled", "orphaned")])
        self.assertFalse(mc._already_waiting(ws, "rerun", "new_start_thread_replies"))

    def test_different_args_are_a_different_job(self):
        ws = _ws([_row("rerun", "new_start_thread_replies --week 2026-10-26", "queued")])
        self.assertFalse(mc._already_waiting(ws, "rerun", "new_start_thread_replies"))

    def test_a_read_error_still_queues(self):
        ws = mock.MagicMock()
        ws.get_all_values.side_effect = RuntimeError("timed out")
        self.assertFalse(mc._already_waiting(ws, "rerun", "x"))


class EnqueueHonoursIt(unittest.TestCase):
    def _enqueue(self, rows, **kw):
        ws = _ws(rows)
        with mock.patch.object(mc, "_open", return_value=ws):
            mc.enqueue("rerun", "new_start_thread_replies", by="Thread Scan",
                       sandbox=True, **kw)
        return ws

    def test_skip_when_one_is_waiting(self):
        ws = self._enqueue([_row("rerun", "new_start_thread_replies", "queued")],
                           skip_if_waiting=True)
        ws.append_row.assert_not_called()

    def test_queue_when_none_is_waiting(self):
        ws = self._enqueue([_row("rerun", "new_start_thread_replies", "done")],
                           skip_if_waiting=True)
        self.assertEqual(ws.append_row.call_count, 1)

    def test_people_are_never_skipped_by_default(self):
        """A human `lucy rerun` means 'run it again' — only schedulers opt in."""
        ws = self._enqueue([_row("rerun", "new_start_thread_replies", "queued")])
        self.assertEqual(ws.append_row.call_count, 1)

    def test_the_flag_is_a_control_flag(self):
        argv = mc._hoist_control_flags(
            ["--enqueue", "rerun", "x", "--skip-if-waiting"])
        self.assertEqual(argv[0], "--skip-if-waiting")


class TheThreadScanUsesIt(unittest.TestCase):
    def test_both_scans_pass_the_flag(self):
        for name in ("new_start_thread_scan.sh", "new_start_number_scan.sh"):
            sh = (Path(mc.REPO_ROOT) / "deploy" / name).read_text()
            self.assertIn("--skip-if-waiting", sh, name)


if __name__ == "__main__":
    unittest.main()
