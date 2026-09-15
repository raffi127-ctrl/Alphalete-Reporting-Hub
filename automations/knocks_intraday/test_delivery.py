"""A board that didn't land is retried, and the day's manifest says what landed.

Run:  PYTHONPATH=. python -m unittest automations.knocks_intraday.test_delivery

WHAT THIS GUARDS (2026-09-14, ticket failure-knocks_intraday): Joseph's 9 PM
board raised on files.completeUploadExternal. Two things went wrong after that:

  · run_slot marked him done anyway (it marked every RENDERED office), so the
    next tick inside GRACE_MIN never retried him.
  · the run wrote no manifest, so delivery_check could never see a clean run
    deliver — the ticket was held open with "nothing can confirm it DELIVERED".

No browser and no Slack: build and the Slack post are stubbed.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.knocks_intraday import schedule, run as intraday
from automations.shared import run_manifest as rm

EOD = schedule.SLOTS_BY_KEY["eod"]
TODAY = dt.date.today()


def rec(key, **over):
    r = {"office": key.title(), "key": key, "label": key.title(),
         "day": TODAY, "abbr": "CST", "channel_id": "C1",
         "channel_name": "#x", "token_file": "", "png": Path(f"{key}.png"),
         "rows": [{}], "error": None}
    r.update(over)
    return r


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.markers = []
        for p in (mock.patch.object(rm, "MANIFEST_DIR", Path(tmp.name)),
                  mock.patch.object(intraday, "record_marker",
                                    self.markers.append),
                  mock.patch.object(intraday, "token_path", lambda r: None),
                  # post() reads the dispositions registry (a live Sheet) to
                  # decide mirror copies — never from a test.
                  mock.patch("automations.knocks_intraday.roster.everyone",
                             lambda: [])):
            p.start()
            self.addCleanup(p.stop)

    def _tick(self, results, fail_keys=()):
        def fake_post(path, **kw):
            if any(f"{k} " in kw["file_name"].lower() for k in fail_keys):
                raise RuntimeError("files.completeUploadExternal failed")
        with mock.patch.object(intraday, "build", lambda s, j, logfn: results), \
             mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image", fake_post):
            return intraday.run_slot(EOD, [object()], dry_run=False,
                                     logfn=lambda m: None)

    def test_a_board_that_raised_on_upload_is_not_marked_done(self):
        rc = self._tick([rec("joseph"), rec("cody")], fail_keys=("joseph",))
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.markers), 1)
        self.assertTrue(self.markers[0].startswith("cody:eod:"))

    def test_the_manifest_names_the_missing_board(self):
        self._tick([rec("joseph"), rec("cody")], fail_keys=("joseph",))
        m = rm.read_manifest(intraday.MANIFEST_ID)
        self.assertEqual(m["failed"], ["joseph:eod"])
        self.assertEqual(m["succeeded"], ["cody:eod"])
        self.assertFalse(m["ok"])

    def test_a_retry_that_lands_clears_the_failure(self):
        self._tick([rec("joseph"), rec("cody")], fail_keys=("joseph",))
        self._tick([rec("joseph")])
        m = rm.read_manifest(intraday.MANIFEST_ID)
        self.assertEqual(m["failed"], [])
        self.assertEqual(m["succeeded"], ["cody:eod", "joseph:eod"])
        self.assertTrue(m["ok"])

    def test_a_later_clean_timezone_does_not_hide_an_earlier_miss(self):
        """The 9 PM slot fires per timezone: the Central tick running clean must
        not erase the Eastern office that failed an hour earlier."""
        self._tick([rec("aya"), rec("joseph")], fail_keys=("joseph",))
        self._tick([rec("cody")])
        m = rm.read_manifest(intraday.MANIFEST_ID)
        self.assertEqual(m["failed"], ["joseph:eod"])

    def test_an_empty_office_counts_as_delivered(self):
        self._tick([rec("salik", png=None, rows=[])])
        m = rm.read_manifest(intraday.MANIFEST_ID)
        self.assertEqual((m["failed"], m["succeeded"]), ([], ["salik:eod"]))

    def test_a_dry_run_writes_nothing(self):
        with mock.patch.object(intraday, "build",
                               lambda s, j, logfn: [rec("cody")]):
            intraday.run_slot(EOD, [object()], dry_run=True, logfn=lambda m: None)
        self.assertIsNone(rm.read_manifest(intraday.MANIFEST_ID))
        self.assertEqual(self.markers, [])


if __name__ == "__main__":
    unittest.main()
