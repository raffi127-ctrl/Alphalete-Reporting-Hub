"""Box Daily Tracker - Rep Lvl in the Box Metrics thread (Carlos 2026-09-23)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from automations.box_order_log import rep_lvl, run


class _Client:
    def __init__(self):
        self.uploads = []

    def chat_postMessage(self, **kw):
        return {"ts": "1.0"}

    def files_upload_v2(self, **kw):
        self.uploads.append(kw["initial_comment"])


class PostThread(unittest.TestCase):
    def _post(self, sections):
        c = _Client()
        with mock.patch("time.sleep"):
            run._post_thread(c, "C1", "hdr", Path("log.xlsx"), Path("pay.png"),
                             Path("tier.png"), "TIER", sections=sections,
                             rep_lvl_path=Path("rl.png"))
        return c.uploads

    def test_rides_right_after_the_tier_board(self):
        ups = self._post({"tier_bonus", "rep_lvl", "accepted"})
        self.assertEqual(ups, ["TIER", rep_lvl.REP_LVL_LINE, run.PAYOUT_LINE])

    def test_left_out_when_not_a_section(self):
        self.assertNotIn(rep_lvl.REP_LVL_LINE, self._post({"tier_bonus"}))

    def test_default_sections_include_it(self):
        self.assertIn(rep_lvl.REP_LVL_LINE,
                      self._post(None))  # None = the standalone default set


if __name__ == "__main__":
    unittest.main()
