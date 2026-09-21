"""The run manifest is the proof of delivery the ticket closer looks for
(shared/delivery_check). Written only after a real sweep got through.

No SaraPlus, no Sheet, no Slack: the sweep itself is stubbed.

    python -m unittest automations.alphalete_sales_board.test_manifest
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.alphalete_sales_board import run as R
from automations.shared import delivery_check, run_manifest
from automations.shared import section_drop_alert


class _Lock:
    held = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Manifest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.order = []
        patches = [
            mock.patch.object(run_manifest, "MANIFEST_DIR", self.tmp),
            # Nothing may reach the channel, the Hub or the state file.
            mock.patch.object(section_drop_alert, "resolved"),
            mock.patch.object(section_drop_alert, "alert"),
            mock.patch.object(R, "Lock", _Lock),
            mock.patch.object(R.TOS, "due", return_value=None),
            mock.patch.object(R.S, "load", return_value={}),
            mock.patch.object(R, "_clear_failures"),
            mock.patch.object(R, "_record_failure"),
            mock.patch.object(R, "_publish_hub_once",
                              side_effect=lambda _d: self.order.append(
                                  ("hub", self.manifest() is not None))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def manifest(self):
        p = self.tmp / (R.HUB_CARD_ID + ".json")
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def test_real_sweep_records_delivery_before_the_hub_row(self):
        with mock.patch.object(R, "sweep", return_value=3):
            self.assertEqual(R.main(["--apply", "--force"]), 0)
        m = self.manifest()
        self.assertIsNotNone(m)
        self.assertTrue(m["ok"])
        self.assertEqual(self.order, [("hub", True)])

    def test_unchanged_board_is_still_a_delivery(self):
        with mock.patch.object(R, "sweep", return_value=0):
            self.assertEqual(R.main(["--apply", "--force"]), 0)
        self.assertIsNotNone(self.manifest())

    def test_preview_and_dry_run_write_nothing(self):
        for argv in (["--force"], ["--apply", "--dry-run", "--force"]):
            with mock.patch.object(R, "sweep", return_value=3):
                self.assertEqual(R.main(argv), 0)
            self.assertIsNone(self.manifest(), argv)

    def test_crash_writes_nothing(self):
        with mock.patch.object(R, "sweep", side_effect=RuntimeError("boom")):
            self.assertEqual(R.main(["--apply", "--force"]), 1)
        self.assertIsNone(self.manifest())

    def test_closer_finds_it_under_either_id(self):
        # The Hub row says 'alphalete-sales-board'; schedule_config says
        # 'alphalete_sales_board'. Both must land on the file just written.
        self.assertIn(R.HUB_CARD_ID,
                      delivery_check.manifest_ids("alphalete_sales_board"))
        self.assertIn(R.HUB_CARD_ID,
                      delivery_check.manifest_ids(R.HUB_CARD_ID))


if __name__ == "__main__":
    unittest.main()
