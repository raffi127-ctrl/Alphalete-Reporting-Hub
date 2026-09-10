"""Offline tests for `review_gate.record_review_posted` — the delivery manifest
that lets this report's ticket close itself (2026-09-10).

The bug it exists for: `verify` was null and the report wrote no manifest, so
`delivery_check` answered UNKNOWN every time and the failure thread stayed open
forever. On 2026-09-10 one sat open all day with all six links posted and every
captain already served.

What these pin down, in order of what would hurt most if it broke:
  * a clean day writes ok=true (that is the write that CLOSES the thread);
  * a day short a block writes it as failed and does NOT ping a second time;
  * a Slack read that fails writes NOTHING — no manifest is UNKNOWN, which
    holds the ticket open, and that is the safe direction;
  * a scoped `--block` run still judges the WHOLE day.

PATCHING THE REAL MODULE, NOT sys.modules — same rule as
test_refresh_stale_blocks.

    python -m unittest automations.captainship_drafts.test_record_review_posted
"""
from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest import mock

from automations.captainship_drafts import config
from automations.captainship_drafts import review_gate as RG


_KEEP_TOKEN: object = None
DAY = dt.date(2026, 9, 10)
PARENT = {"ts": "1789050799.929089"}


def setUpModule():
    global _KEEP_TOKEN
    _KEEP_TOKEN = os.environ.get("SLACK_USER_TOKEN")
    os.environ["SLACK_USER_TOKEN"] = "xoxp-not-a-real-token-unit-test"


def tearDownModule():
    if _KEEP_TOKEN is None:
        os.environ.pop("SLACK_USER_TOKEN", None)
    else:
        os.environ["SLACK_USER_TOKEN"] = _KEEP_TOKEN


def _thread(keys):
    """{block key: its link message} as block_posts would return it."""
    return {k: {"ts": "1789050800.{}".format(i)} for i, k in enumerate(keys)}


class RecordReviewPosted(unittest.TestCase):

    def setUp(self):
        self.written = []
        p = mock.patch("automations.shared.run_manifest.write_manifest",
                       side_effect=lambda *a, **kw: self.written.append((a, kw)))
        p.start()
        self.addCleanup(p.stop)
        self.all_keys = [b.key for b in config.BLOCKS]

    # ---------------------------------------------------------------- clean --

    def test_every_block_up_writes_a_clean_manifest(self):
        with mock.patch.object(RG, "_find_post", return_value=PARENT), \
             mock.patch.object(RG, "block_posts",
                               return_value=_thread(self.all_keys)):
            got = RG.record_review_posted(DAY, "C0BLLU9M0A2", verbose=False)
        self.assertEqual(got["failed"], [])
        self.assertEqual(got["succeeded"], self.all_keys)
        (args, kw), = self.written
        self.assertEqual(args[0], RG.REPORT_ID,
                         "the manifest has to be filed under the id "
                         "delivery_check looks for")
        self.assertEqual(kw["failed"], [])
        self.assertEqual(kw["succeeded"], self.all_keys)
        self.assertEqual(kw["kind"], "block")
        self.assertEqual(kw["retry_args"], ["--ensure-posted"])

    def test_a_clean_run_is_allowed_to_speak(self):
        """`alert=True` on the clean write is what closes an open thread —
        write_manifest calls section_drop_alert.resolved on that branch."""
        with mock.patch.object(RG, "_find_post", return_value=PARENT), \
             mock.patch.object(RG, "block_posts",
                               return_value=_thread(self.all_keys)):
            RG.record_review_posted(DAY, verbose=False)
        (_, kw), = self.written
        self.assertTrue(kw["alert"])

    # -------------------------------------------------------------- partial --

    def test_a_missing_block_is_recorded_as_failed(self):
        up = self.all_keys[:-1]
        missing = self.all_keys[-1]
        with mock.patch.object(RG, "_find_post", return_value=PARENT), \
             mock.patch.object(RG, "block_posts", return_value=_thread(up)):
            got = RG.record_review_posted(DAY, verbose=False)
        self.assertEqual(got["failed"], [missing])
        self.assertEqual(got["succeeded"], up)
        (_, kw), = self.written
        self.assertEqual(kw["failed"], [missing])

    def test_a_missing_block_does_not_ping_a_second_time(self):
        """_alert_deadline_failure and --close-day already name it. Two posts
        for one miss is the duplicate-post problem, not extra safety."""
        with mock.patch.object(RG, "_find_post", return_value=PARENT), \
             mock.patch.object(RG, "block_posts",
                               return_value=_thread(self.all_keys[:-1])):
            RG.record_review_posted(DAY, verbose=False)
        (_, kw), = self.written
        self.assertFalse(kw["alert"])

    def test_no_parent_post_means_nothing_delivered(self):
        with mock.patch.object(RG, "_find_post", return_value=None), \
             mock.patch.object(RG, "block_posts",
                               side_effect=AssertionError("no parent to read")):
            got = RG.record_review_posted(DAY, verbose=False)
        self.assertEqual(got["succeeded"], [])
        self.assertEqual(got["failed"], self.all_keys)

    # -------------------------------------------------------------- unknown --

    def test_a_failed_slack_read_writes_no_manifest_at_all(self):
        """No manifest is UNKNOWN, which HOLDS the ticket open. Claiming a
        delivery we could not see is the one direction this must never fail."""
        with mock.patch.object(RG, "_find_post",
                               side_effect=RuntimeError("slack down")):
            got = RG.record_review_posted(DAY, verbose=False)
        self.assertIsNone(got)
        self.assertEqual(self.written, [],
                         "a read we could not do must not become a verdict")

    # --------------------------------------------------------------- scoped --

    def test_a_scoped_run_still_judges_the_whole_day(self):
        """`--post --block nds` must not write a manifest saying the day was
        one block long and clean."""
        self.assertGreater(len(self.all_keys), 1)
        with mock.patch.object(RG, "_find_post", return_value=PARENT), \
             mock.patch.object(RG, "block_posts",
                               return_value=_thread([self.all_keys[-1]])):
            got = RG.record_review_posted(DAY, verbose=False)
        self.assertEqual(got["failed"], self.all_keys[:-1])
        self.assertIn("1 of {}".format(len(self.all_keys)), got["note"])

    # ----------------------------------------------------------- the wiring --

    def test_the_config_asks_for_this_manifest(self):
        """The verify block and the id the manifest is written under have to
        agree, or delivery_check looks in the wrong place."""
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(RG.__file__).resolve().parents[2] / "automations" /
             "day_orchestrator" / "schedule_config.json").read_text("utf-8"))
        v = cfg["reports"]["captainship_drafts_review"]["verify"]
        self.assertEqual(v, {"type": "manifest",
                             "report_id": RG.REPORT_ID})


if __name__ == "__main__":
    unittest.main()
