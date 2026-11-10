"""Lucy can't read Google reviews -> the manager hears about it.

    python -m unittest automations.online_presence.test_key_watch

Google and Slack are fakes: nothing is read or posted for real.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.online_presence import key_watch as K, rooms


class FakeSlack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": f"1.{len(self.posts)}"}


T0 = dt.datetime(2026, 11, 10, 9, 0)


class Watch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = mock.patch.object(K, "STATE", Path(self.tmp.name) / "w.json")
        self.state.start()
        self.cl = FakeSlack()

    def tearDown(self):
        self.state.stop()
        self.tmp.cleanup()

    def _check(self, bad, now=T0, live=True):
        with mock.patch.object(K, "probe", return_value=bad), \
                mock.patch.object(K, "_machine", return_value="Lucy 3"):
            return K.check(live=live, cl=self.cl, location="accounts/1/locations/2", now=now)

    def test_missing_key_alerts_right_away_channel_and_manager(self):
        acts = self._check(("missing", "Google's review key isn't on this computer"))
        self.assertEqual(acts[0]["action"], "alert")
        chans = [p["channel"] for p in self.cl.posts]
        self.assertEqual(chans, [rooms.SOCIAL_ALERTS, rooms.SOCIAL_ALERTS, rooms.MANAGER])
        self.assertNotIn("thread_ts", self.cl.posts[0])                # short header
        self.assertIn("Lucy 3", self.cl.posts[1]["text"])               # detail in the thread
        self.assertIn("every LucyECO Social office", self.cl.posts[1]["text"])

    def test_reminds_once_a_day_not_every_pass(self):
        bad = ("missing", "x")
        self._check(bad)
        self._check(bad, now=T0 + dt.timedelta(minutes=10))
        self.assertEqual(len(self.cl.posts), 3)
        self._check(bad, now=T0 + dt.timedelta(days=1))
        self.assertEqual(len(self.cl.posts), 6)

    def test_a_blip_waits_for_three_passes(self):
        bad = ("error", "Google's review API isn't answering (Timeout)")
        self.assertEqual(self._check(bad)[0]["action"], "watching")
        self.assertEqual(self._check(bad)[0]["action"], "watching")
        self.assertEqual(self._check(bad)[0]["action"], "alert")

    def test_back_working_says_so_once(self):
        self._check(("expired", "expired"))
        n = len(self.cl.posts)
        self.assertEqual(self._check(None)[0]["action"], "recovered")
        self.assertIn("working again", self.cl.posts[n]["text"])
        self.assertEqual(self._check(None)[0]["action"], "ok")
        self.assertEqual(len(self.cl.posts), n + 2)

    def test_a_blip_that_clears_never_alerts(self):
        self._check(("error", "x"))
        self.assertEqual(self._check(None)[0]["action"], "ok")
        self.assertEqual(self.cl.posts, [])

    def test_dry_sends_nothing(self):
        self.assertEqual(self._check(("missing", "x"), live=False)[0]["action"], "would_alert")
        self.assertEqual(self.cl.posts, [])

    def test_manager_is_in_every_new_office_channel(self):
        with mock.patch("automations.shared.slack_metrics_post._load_bot_token",
                        side_effect=Exception("no Lucy app token here")), \
                mock.patch("automations.online_presence.setup.resolve_person", side_effect=ValueError("nobody")):
            ids, _ = rooms._people({"Owner": ""}, mock.Mock())
        self.assertIn(rooms.MANAGER, ids)


class Probe(unittest.TestCase):
    def test_no_key_file_is_missing(self):
        from automations.brand_audit import gbp_api
        with mock.patch.object(gbp_api, "has_token", return_value=False):
            self.assertEqual(K.probe("loc")[0], "missing")

    def test_refused_and_expired(self):
        from automations.brand_audit import gbp_api
        with mock.patch.object(gbp_api, "has_token", return_value=True), \
                mock.patch.object(gbp_api, "list_reviews", side_effect=gbp_api.GBPAccessError("403")):
            self.assertEqual(K.probe("loc")[0], "refused")
        with mock.patch.object(gbp_api, "has_token", return_value=True), \
                mock.patch.object(gbp_api, "list_reviews",
                                  side_effect=RuntimeError("Business Profile token is invalid and can't be refreshed")):
            self.assertEqual(K.probe("loc")[0], "expired")


if __name__ == "__main__":
    unittest.main()
