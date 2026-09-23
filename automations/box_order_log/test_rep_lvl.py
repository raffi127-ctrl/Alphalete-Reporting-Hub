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


class ContentsBackfill(unittest.TestCase):
    """backfill_tier --board rep_lvl: the line goes into the contents reply
    (found by content, not position), once, and comes back off any caption it
    got glued onto (the live thread, 2026-09-23)."""

    def _client(self, *texts):
        c = mock.Mock()
        msgs = [{"ts": "1.0", "text": "parent"}]
        msgs += [{"ts": "1.{}".format(i + 1), "text": t}
                 for i, t in enumerate(texts)]
        c.conversations_replies.return_value = {"messages": msgs}
        return c

    def _contents(self, *extra):
        return "\n".join([":bar_chart: Rev", ":trophy: Box Tier Bonus Rep Level"]
                         + list(extra) + [run.WORKBOOK_LINE])

    def test_inserted_under_the_tier_line(self):
        from automations.box_order_log import backfill_tier
        c = self._client(self._contents())
        backfill_tier._add_to_contents(c, "C1", "1.0")
        kw = c.chat_update.call_args.kwargs
        self.assertEqual(kw["ts"], "1.1")
        self.assertEqual(kw["text"].split("\n")[2], rep_lvl.REP_LVL_LINE)

    def test_not_added_twice(self):
        from automations.box_order_log import backfill_tier
        c = self._client(self._contents(":clipboard: " + rep_lvl.BOARD_NAME))
        backfill_tier._add_to_contents(c, "C1", "1.0")
        c.chat_update.assert_not_called()

    def test_repairs_the_glued_caption(self):
        from automations.box_order_log import backfill_tier
        glued = ":clipboard: {}\n:moneybag: BOX Revenue by Status".format(
            rep_lvl.BOARD_NAME)
        c = self._client(self._contents(), ":zap: Act", glued,
                         ":clipboard: " + rep_lvl.BOARD_NAME)
        backfill_tier._add_to_contents(c, "C1", "1.0")
        calls = {k.kwargs["ts"]: k.kwargs["text"]
                 for k in c.chat_update.call_args_list}
        self.assertEqual(calls["1.3"], ":moneybag: BOX Revenue by Status")
        self.assertIn(rep_lvl.BOARD_NAME, calls["1.1"])
        self.assertNotIn("1.4", calls)          # the image reply is left alone


if __name__ == "__main__":
    unittest.main()
