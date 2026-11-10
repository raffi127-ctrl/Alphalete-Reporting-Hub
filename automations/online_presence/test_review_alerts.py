"""Bad Google review → the office's room, the owner, the alerts channel.

    python -m unittest automations.online_presence.test_review_alerts

Google and Slack are faked; nothing is sent.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.online_presence.rooms import SOCIAL_ALERTS as ALERT_SLACK_CHANNEL_ID
from automations.online_presence import offices, review_alerts as RA


class FakeSlack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "9.%d" % len(self.posts)}


def _rv(i, stars, text="meh", replied=False):
    return {"review_id": f"R{i}", "name": f"accounts/1/locations/2/reviews/R{i}",
            "rating": stars, "text": text, "author": f"Person {i}",
            "publish_time": "2026-11-09T10:00:00Z", "has_reply": replied}


class Alerts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        self.p = offices.Presence(key="kash", business_name="Kash Marketing",
                                  slack_channel="C0KASHROOM", owner_slack_id="U046XBPN0G2",
                                  gbp_location="accounts/1/locations/2")

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def _run(self, reviews, live=True):
        cl = FakeSlack()
        return RA.check(self.p, cl, live=live, reviews=reviews), cl

    def test_first_look_seeds_and_sends_nothing(self):
        acts, cl = self._run([_rv(1, 1), _rv(2, 2)])
        self.assertEqual(acts[0]["action"], "seeded")
        self.assertEqual(cl.posts, [])

    def test_new_bad_review_goes_to_room_alerts_channel_and_owner(self):
        self._run([_rv(1, 5)])                                    # seed
        acts, cl = self._run([_rv(2, 2, "rude rep"), _rv(1, 5)])
        self.assertEqual([a["action"] for a in acts], ["bad_review_alert"])
        chans = [p["channel"] for p in cl.posts]
        self.assertEqual(chans.count("C0KASHROOM"), 2)            # header + thread
        self.assertEqual(chans.count(ALERT_SLACK_CHANNEL_ID), 2)
        self.assertIn("U046XBPN0G2", chans)                       # the owner's DM
        header = cl.posts[0]
        self.assertNotIn("thread_ts", header)
        self.assertIn("2★", header["text"])
        self.assertIn("rude rep", cl.posts[1]["text"])            # detail in the thread

    def test_once_only(self):
        self._run([_rv(1, 5)])
        self._run([_rv(2, 1), _rv(1, 5)])
        acts, cl = self._run([_rv(2, 1), _rv(1, 5)])
        self.assertEqual((acts, cl.posts), ([], []))

    def test_good_and_already_answered_stay_quiet(self):
        self._run([_rv(1, 5)])
        acts, cl = self._run([_rv(2, 5), _rv(3, 4), _rv(4, 2, replied=True), _rv(1, 5)])
        self.assertEqual(cl.posts, [])

    def test_edited_down_to_two_stars_alerts(self):
        self._run([_rv(1, 5)])
        acts, cl = self._run([_rv(1, 2)])
        self.assertEqual(acts[0]["action"], "bad_review_alert")

    def test_dry_sends_and_saves_nothing(self):
        self._run([_rv(1, 5)])
        acts, cl = self._run([_rv(2, 1), _rv(1, 5)], live=False)
        self.assertEqual(acts[0]["action"], "would_alert")
        self.assertEqual(cl.posts, [])
        acts, cl = self._run([_rv(2, 1), _rv(1, 5)])               # still new on the live pass
        self.assertEqual(acts[0]["action"], "bad_review_alert")

    def test_alphalete_alerts_only_its_own_channel(self):
        a = offices.alphalete()
        with mock.patch.object(offices.Presence, "path",
                               lambda self, n: Path(self.folder if False else tempfile.gettempdir())
                               / f"ra_test_{n}"):
            Path(tempfile.gettempdir(), "ra_test_review_alerts.json").unlink(missing_ok=True)
            RA.check(a, FakeSlack(), live=True, reviews=[_rv(1, 5)])
            cl = FakeSlack()
            RA.check(a, cl, live=True, reviews=[_rv(2, 1), _rv(1, 5)])
            Path(tempfile.gettempdir(), "ra_test_review_alerts.json").unlink(missing_ok=True)
        self.assertEqual({p["channel"] for p in cl.posts}, {a.reviews_channel})

    def test_no_listing_no_check(self):
        p = offices.Presence(key="k", business_name="K", slack_channel="C1")
        self.assertEqual(RA.check(p, FakeSlack(), live=True, reviews=[_rv(1, 1)]), [])


if __name__ == "__main__":
    unittest.main()
