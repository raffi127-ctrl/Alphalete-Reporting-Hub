"""A tier board that loses the ownerville race is retried, not dropped.

2026-11-21: Ryan McSpadden's per-office Box thread posted at 9:01 without its
Box Tier Bonus board because three other Lucy 2 runs held the ownerville
session for the whole 30-minute wait. Nothing ever tried the board again.

    python -m unittest automations.box_order_log.test_tier_retry
"""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from automations.box_order_log import per_office, run as boxrun

BUSY = ("OwnervilleBusy: another run on this machine has held the ownerville "
        "session for the whole 1800s this run could wait")
DAY = dt.date(2026, 11, 21)


class QueueTierRetry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "q.jsonl"

    def _queue(self, note, ids=("C1",), env=True):
        patch = {boxrun.TIER_RETRY_ENV: str(self.tmp)} if env else {}
        with mock.patch.dict(os.environ, patch, clear=False):
            if not env:
                os.environ.pop(boxrun.TIER_RETRY_ENV, None)
            return boxrun.queue_tier_retry(list(ids), "Ryan McSpadden", DAY, note)

    def test_busy_session_is_queued(self):
        self.assertTrue(self._queue(BUSY))
        row = json.loads(self.tmp.read_text().splitlines()[0])
        self.assertEqual(row["channel"], "C1")
        self.assertEqual(row["owner"], "Ryan McSpadden")
        self.assertEqual(row["date"], "2026-11-21")

    def test_real_capture_failure_still_alerts(self):
        # a moved filter is not a race; the caller must alert right away
        self.assertFalse(self._queue("TimeoutError: filter never rendered"))
        self.assertFalse(self.tmp.exists())

    def test_standalone_run_without_queue_alerts(self):
        self.assertFalse(self._queue(BUSY, env=False))

    def test_nothing_posted_is_not_queued(self):
        self.assertFalse(self._queue(BUSY, ids=()))


class RetryTierBoards(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "q.jsonl"
        self.tmp.write_text(json.dumps({"channel": "C1", "owner": "Ryan McSpadden",
                                        "date": "2026-11-21", "note": BUSY}) + "\n")

    def _run(self, codes):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            return SimpleNamespace(returncode=codes[len(calls) - 1])

        with mock.patch("automations.shared.section_drop_alert.alert") as alert:
            still = per_office.retry_tier_boards(self.tmp, attempts=2,
                                                 runner=runner)
        return still, calls, alert

    def test_second_try_wins_no_alert(self):
        still, calls, alert = self._run([1, 0])
        self.assertEqual(still, [])
        self.assertEqual(len(calls), 2)
        self.assertIn("automations.box_order_log.backfill_tier", calls[0])
        self.assertEqual(calls[0][calls[0].index("--channel") + 1], "C1")
        self.assertIn("--post", calls[0])
        alert.assert_not_called()
        self.assertFalse(self.tmp.exists())

    def test_every_try_fails_alerts_once(self):
        still, calls, alert = self._run([1, 1])
        self.assertEqual(len(still), 1)
        self.assertEqual(len(calls), 2)
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["report_id"],
                         "box-order-log-per-office")

    def test_empty_queue_is_a_no_op(self):
        missing = self.tmp.with_name("none.jsonl")
        self.assertEqual(per_office.retry_tier_boards(missing), [])


if __name__ == "__main__":
    unittest.main()
