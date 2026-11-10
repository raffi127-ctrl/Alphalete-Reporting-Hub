"""Every review an office has gets a response -- old ones too, paced.

    python -m unittest automations.online_presence.test_review_backlog

Slack, Google and Claude are fakes: nothing is posted or drafted for real.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.brand_audit import review_replies as R
from automations.online_presence import offices


class FakeSlack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": f"1.{len(self.posts)}"}

    def conversations_replies(self, **kw):
        return {"messages": []}


def _office():
    return offices.Presence(key="kash", business_name="Kash Marketing",
                            slack_channel="C0KASH", approvers=("U1",),
                            gbp_location="accounts/1/locations/2")


def _reviews(good=0, bad=0):
    out = [{"name": f"r/good{i}", "review_id": f"g{i}", "rating": 5, "text": "great",
            "author": f"G{i}", "has_reply": False} for i in range(good)]
    out += [{"name": f"r/bad{i}", "review_id": f"b{i}", "rating": 2, "text": "meh",
             "author": f"B{i}", "has_reply": False} for i in range(bad)]
    return out


class Backlog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        self.cl = FakeSlack()
        self.posted = []

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def _run(self, reviews, post=None, dry=False):
        post = post or (lambda rv, reply, company: self.posted.append(rv["name"]))
        with mock.patch.object(R, "_client", return_value=self.cl), \
                mock.patch.object(R, "gbp_ready", return_value=True), \
                mock.patch.object(R, "get_reviews", return_value=reviews), \
                mock.patch.object(R, "draft_reply", return_value="Thanks!"), \
                mock.patch.object(R, "post_reply_to_google", side_effect=post):
            return R.process_reviews(dry_run=dry, profile=_office())

    def _cards(self):
        return [p for p in self.cl.posts if "thread_ts" not in p and "Response Reviews" not in p["text"]]

    def test_old_bad_reviews_come_a_few_a_day_then_the_rest(self):
        revs = _reviews(bad=12)
        acts = self._run(revs)
        self.assertEqual(len(self._cards()), 5)                       # day 1: 5 cards
        self.assertIn("5 cards for ✅/day", next(a["note"] for a in acts if a["action"] == "deferred"))
        self._run(revs)                                                # same day: no more
        self.assertEqual(len(self._cards()), 5)

    def test_old_good_reviews_all_answered_over_the_days(self):
        self._run(_reviews(good=14))
        self.assertEqual(len(self.posted), 10)                         # the office's daily cap

    def test_a_failed_auto_reply_is_tried_again(self):
        def flaky(rv, reply, company):
            raise RuntimeError("Google blip")
        self._run(_reviews(good=1), post=flaky)
        self.assertEqual(self.posted, [])
        acts = self._run([])                                           # next pass, Google back
        self.assertIn("retry_post", [a["action"] for a in acts])
        self.assertEqual(self.posted, ["r/good0"])
        acts = self._run([])
        self.assertNotIn("retry_post", [a["action"] for a in acts])    # never twice

    def test_alphalete_has_no_card_limit(self):
        self.assertEqual(offices.alphalete().review_draft_daily_cap, 0)


if __name__ == "__main__":
    unittest.main()
