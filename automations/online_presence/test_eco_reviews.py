"""Google reviews through the office's own computer (eco_reviews.py).

    python -m unittest automations.online_presence.test_eco_reviews

Relay, Slack, Google and Claude are fakes: nothing is queued or posted.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from automations.brand_audit import review_replies as RR
from automations.online_presence import eco_reviews as E, offices, relay


class FakeSlack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": f"1.{len(self.posts)}"}

    def conversations_replies(self, **kw):
        return {"messages": []}


def _office(**kw):
    return offices.Presence(key="kash", business_name="Kash Marketing", slack_channel="C0KASH",
                            approvers=("U1",), gbp_location="accounts/9/locations/22",
                            owner_slack_id="UOWN", reviews_via="eco", **kw)


def _ans(do, **res):
    return {"job_id": "j-" + do, "kind": "social_check", "office": "kash",
            "answered": True, "result": dict(res, do=do)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        self.P, self.cl = _office(), FakeSlack()
        self.queued = []
        self.q = mock.patch.object(relay, "enqueue",
                                   side_effect=lambda o, k, pl, live: self.queued.append((k, pl)) or "J%d" % len(self.queued))
        self.q.start()

    def tearDown(self):
        self.q.stop()
        self.root.stop()
        self.tmp.cleanup()

    def signed_in(self):
        E.collect(self.P, [_ans("google_signin", status="signed_in",
                                listings=[{"path": "accounts/555/locations/22", "title": "Kash"},
                                          {"path": "accounts/555/locations/77", "title": "Other"}])],
                  self.cl, dry=False)


class SignIn(Base):
    def test_picks_the_owner_listing_that_matches_signup(self):
        self.signed_in()
        self.assertTrue(E.signed_in(self.P))
        self.assertEqual(E._load(self.P)["location"], "accounts/555/locations/22")

    def test_no_match_is_not_signed_in(self):
        E.collect(self.P, [_ans("google_signin", status="signed_in",
                                listings=[{"path": "a/1/locations/5", "title": "X"},
                                          {"path": "a/1/locations/6", "title": "Y"}])], self.cl, dry=False)
        self.assertFalse(E.signed_in(self.P))

    def test_signin_job_rides_social_check(self):
        with mock.patch.object(E, "_client_details", return_value=("cid", "sec")):
            E.queue_signin(self.P)
        kind, pl = self.queued[0]
        self.assertEqual((kind, pl["do"]), ("social_check", "google_signin"))


class SplitFromZoho(unittest.TestCase):
    def test_review_answers_never_reach_the_zoho_watcher(self):
        zoho = {"job_id": "z", "kind": "social_check", "result": {"status": "ok", "channels": []}}
        ours, rest = E.split([zoho, _ans("google_reviews", status="ok")])
        self.assertEqual([r["job_id"] for r in rest], ["z"])
        self.assertEqual(len(ours), 1)


class ReadAndReply(Base):
    def test_reads_every_30_min_one_at_a_time(self):
        self.signed_in()
        self.assertEqual(E.ensure_read(self.P, live=True)["action"], "review_read_queued")
        self.assertIsNone(E.ensure_read(self.P, live=True))          # one pending
        E.collect(self.P, [_ans("google_reviews", status="ok", reviews=[])], self.cl, dry=False)
        self.assertIsNone(E.ensure_read(self.P, live=True))          # read just now
        self.assertEqual(len(self.queued), 1)

    def test_practice_queues_nothing(self):
        self.signed_in()
        self.assertEqual(E.ensure_read(self.P, live=False)["action"], "would_queue_review_read")
        self.assertEqual(self.queued, [])

    def _pass(self, revs):
        with mock.patch.object(RR, "_client", return_value=self.cl), \
             mock.patch.object(RR, "draft_reply", return_value="Thank you!"):
            return RR.process_reviews(dry_run=False, profile=self.P, fetch=lambda: revs,
                                      post=E.poster(self.P), can_post=True)

    def test_good_review_queues_a_reply_to_the_office_computer(self):
        self.signed_in()
        E.collect(self.P, [_ans("google_reviews", status="ok", reviews=[
            {"name": "accounts/555/locations/22/reviews/a", "rating": 5, "text": "great",
             "author": "Ann", "time": "2026-11-15T10:00:00Z"}])], self.cl, dry=False)
        acts = self._pass(E.reviews(self.P))
        self.assertIn("auto_post", [a["action"] for a in acts])
        kind, pl = self.queued[-1]
        self.assertEqual((kind, pl["do"], pl["comment"]), ("social_post", "google_reply", "Thank you!"))
        self.assertEqual(pl["name"], "accounts/555/locations/22/reviews/a")

    def test_bad_review_waits_for_the_check_mark(self):
        acts = self._pass([{"name": "r/b", "rating": 1, "text": "bad", "author": "B",
                            "publish_time": "t"}])
        self.assertEqual([a["action"] for a in acts if a["action"] in ("draft", "auto_post")], ["draft"])
        self.assertEqual(self.queued, [])

    def test_a_failed_reply_is_tried_again(self):
        self._pass([{"name": "r/a", "rating": 5, "text": "great", "author": "A", "publish_time": "t"}])
        E.collect(self.P, [_ans("google_reply", status="error", error="boom", name="r/a")], self.cl, dry=False)
        before = len(self.queued)
        acts = self._pass([])
        self.assertIn("retry_post", [a["action"] for a in acts])
        self.assertEqual(len(self.queued), before + 1)

    def test_signed_out_dms_the_owner_once_a_day(self):
        self.signed_in()
        for _ in range(2):
            E.collect(self.P, [_ans("google_reviews", status="signed_out")], self.cl, dry=False)
        self.assertEqual([p["channel"] for p in self.cl.posts], ["UOWN"])
        self.assertFalse(E.signed_in(self.P))


class OfficeRow(unittest.TestCase):
    def test_reviews_via_must_be_eco_or_lucy(self):
        self.assertTrue(any("reviews_via" in x for x in replace(_office(), reviews_via="x").problems()))
        self.assertFalse(any("reviews_via" in x for x in _office().problems()))


if __name__ == "__main__":
    unittest.main()
