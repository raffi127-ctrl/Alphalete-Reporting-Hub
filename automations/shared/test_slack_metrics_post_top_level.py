"""top_level: post to the CHANNEL, not into the day's Metrics thread.

Megan 2026-08-25, of the knocks boards: "should NOT go in a thread but just be
posted to the channel so everyone can see it". The flag must default OFF, so the
dozens of existing metrics callers keep threading exactly as before.
"""
import datetime as dt
import unittest
from pathlib import Path

from automations.shared import slack_metrics_post as smp


class _FakeClient:
    def __init__(self):
        self.uploads = []
        self.reactions = []

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        return {"ok": True, "file": {"id": "F1"}}

    def reactions_add(self, **kw):
        self.reactions.append(kw)
        return {"ok": True}

    def conversations_replies(self, **kw):
        return {"messages": []}


class TopLevelPosting(unittest.TestCase):
    def setUp(self):
        self.client = _FakeClient()
        self._real_client = smp._client
        self._real_find = smp.find_metrics_thread_ts
        self._real_mirrors = smp.mirror_channels
        smp._client = lambda: self.client
        smp.find_metrics_thread_ts = lambda c, d: "1111.2222"
        smp.mirror_channels = lambda c: []

    def tearDown(self):
        smp._client = self._real_client
        smp.find_metrics_thread_ts = self._real_find
        smp.mirror_channels = self._real_mirrors

    def _post(self, **kw):
        return smp.post_reply_with_image(
            Path("x.png"), comment="c", today=dt.date(2026, 8, 25),
            channel_id="C1", **kw)

    def test_default_still_threads(self):
        """Every existing caller must be untouched."""
        self._post()
        self.assertEqual(self.client.uploads[0]["thread_ts"], "1111.2222")

    def test_top_level_posts_with_no_thread(self):
        self._post(top_level=True)
        self.assertIsNone(self.client.uploads[0]["thread_ts"])

    def test_top_level_does_not_look_up_the_metrics_thread(self):
        """Not just unused — never fetched. A lookup that fails must not be able
        to take down a post that doesn't need it."""
        def _boom(c, d):
            raise AssertionError("find_metrics_thread_ts called for a top-level post")
        smp.find_metrics_thread_ts = _boom
        self._post(top_level=True)          # must not raise

    def test_top_level_skips_the_reaction(self):
        """reactions_add needs a message ts; a top-level post has none, so the
        call would fail on a None timestamp."""
        self._post(top_level=True, react_emoji="door")
        self.assertEqual(self.client.reactions, [])

    def test_threaded_still_reacts(self):
        self._post(react_emoji="door")
        self.assertEqual(self.client.reactions[0]["timestamp"], "1111.2222")


if __name__ == "__main__":
    unittest.main()
