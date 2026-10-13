"""A held headcount board that posts late re-queues the Org Active Headcount
daily (Eve 2026-10-13: the NDS Tracker came in late, 12 owners read 0)."""
import unittest
from unittest import mock

from automations.day_orchestrator import mini_control as mc
from automations.day_orchestrator import notify
from automations.tableau_screenshots import run as ts_run


class HeadcountRefillTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(mc, "enqueue")
        self.enqueue = p.start()
        self.addCleanup(p.stop)
        # never a real Slack post from a test
        a = mock.patch.object(notify, "post_alert")
        self.alert = a.start()
        self.addCleanup(a.stop)

    def test_late_nds_queues_the_daily(self):
        ts_run._queue_headcount_refill({"nds"}, posted_alphalete=True)
        self.enqueue.assert_called_once_with(
            "rerun", "org_active_headcount_daily --late",
            by="tableau_screenshots", auto=True)

    def test_board_the_daily_does_not_read(self):
        ts_run._queue_headcount_refill({"quantum_fiber"}, posted_alphalete=True)
        self.enqueue.assert_not_called()

    def test_not_posted_to_the_alphalete_thread(self):
        ts_run._queue_headcount_refill({"nds"}, posted_alphalete=False)
        self.enqueue.assert_not_called()

    def test_queue_failure_alerts_and_does_not_raise(self):
        self.enqueue.side_effect = RuntimeError("sheet down")
        ts_run._queue_headcount_refill({"b2b_box"}, posted_alphalete=True)
        self.alert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
