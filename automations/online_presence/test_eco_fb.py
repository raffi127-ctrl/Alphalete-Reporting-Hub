"""Facebook reviews through the office's own computer (eco_fb.py).

    python -m unittest automations.online_presence.test_eco_fb

Relay, Slack and Claude are fakes: nothing is queued or posted.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.brand_audit import fb_reviews, review_replies as RR
from automations.online_presence import eco_fb as E, offices, relay


class FakeSlack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "1.%d" % len(self.posts)}


def _ans(do, **res):
    return {"job_id": "j", "kind": "social_check", "office": "kash", "answered": True, "result": dict(res, do=do)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        self.P = offices.Presence(key="kash", business_name="Kash", slack_channel="C1", approvers=("U1",),
                                  facebook_page_id="9", reviews_via="eco")
        self.cl, self.queued = FakeSlack(), []
        self.q = mock.patch.object(relay, "enqueue",
                                   side_effect=lambda o, k, pl, live: self.queued.append((k, pl)) or "J")
        self.q.start()
        E.collect(self.P, [_ans("fb_key", status="connected", page="Kash")], self.cl, dry=False)

    def tearDown(self):
        self.q.stop()
        self.root.stop()
        self.tmp.cleanup()

    def _pass(self, revs):
        with mock.patch.object(RR, "_client", return_value=self.cl), \
             mock.patch.object(RR, "draft_reply", return_value="Thank you!"), \
             mock.patch.object(fb_reviews, "_keys", side_effect=AssertionError("Meta key used")):
            return fb_reviews.process(live=True, profile=self.P, reviews=revs, post=E.poster(self.P))


class Flow(Base):
    def test_connected_then_reads_every_30_min(self):
        self.assertTrue(E.connected(self.P))
        self.assertEqual(E.ensure_read(self.P, live=True)["action"], "fb_read_queued")
        self.assertIsNone(E.ensure_read(self.P, live=True))
        self.assertEqual(self.queued[0][1]["do"], "fb_reviews")

    def test_thank_you_queued_to_the_office_without_any_meta_key(self):
        E.collect(self.P, [_ans("fb_reviews", status="ok", reviews=[
            {"story": "s1", "recommendation_type": "positive", "review_text": "great"}])], self.cl, dry=False)
        acts = self._pass(E.reviews(self.P))
        self.assertEqual([a["action"] for a in acts], ["auto_post"])
        self.assertEqual(self.queued[-1], ("social_post", {"do": "fb_reply", "story": "s1", "comment": "Thank you!"}))

    def test_doesnt_recommend_waits_for_check_mark(self):
        acts = self._pass([{"open_graph_story": {"id": "s2"}, "recommendation_type": "negative"}])
        self.assertEqual([a["action"] for a in acts], ["draft"])
        self.assertEqual(self.queued, [])

    def test_failed_thank_you_is_read_again(self):
        self._pass([{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}])
        E.collect(self.P, [_ans("fb_reply", status="error", error="boom", story="s1")], self.cl, dry=False)
        st = json.loads(self.P.path("fb_review_replies.json").read_text())
        self.assertNotIn("s1", st["reviews"])

    def _st(self):
        return json.loads(self.P.path("fb_review_replies.json").read_text())

    def test_facebook_refusal_parks_the_review_and_it_is_never_sent_again(self):
        # 11/15-16: "Permissions error" thank-yous looped 140+ times.
        self._pass([{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}])
        acts = E.collect(self.P, [_ans("fb_reply", status="error", error="Permissions error", story="s1")],
                         self.cl, dry=False)
        self.assertEqual(acts[0]["action"], "fb_reply_blocked")
        self.assertIn("s1", self._st()["reviews"])
        self.assertTrue(self._st()["reviews"]["s1"]["blocked"])
        n = len(self.queued)
        self.assertEqual(self._pass([{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}]), [])
        self.assertEqual(len(self.queued), n, "a blocked review was sent again")
        E.ensure_read(self.P, live=True)
        self.assertIn("s1", self.queued[-1][1]["skip"])

    def test_second_failure_of_anything_parks_it(self):
        revs = [{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}]
        self._pass(revs)
        E.collect(self.P, [_ans("fb_reply", status="error", error="boom", story="s1")], self.cl, dry=False)
        self._pass(revs)
        acts = E.collect(self.P, [_ans("fb_reply", status="error", error="boom", story="s1")], self.cl, dry=False)
        self.assertEqual(acts[0]["action"], "fb_reply_blocked")

    def test_a_page_that_never_posted_says_so_as_well_as_parking(self):
        # raf 2026-11-16: 70 refusals, ZERO successful replies, all day. If
        # that is the page key missing pages_manage_engagement, parking every
        # review quietly stops answering Facebook altogether while the pass
        # still reports success. The parking stays (no retry loop); this is the
        # line that keeps it from being silent.
        self._pass([{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}])
        acts = E.collect(self.P, [_ans("fb_reply", status="error",
                                       error="(#200) Permissions error", story="s1")],
                         self.cl, dry=False)
        names = [a["action"] for a in acts]
        self.assertIn("fb_reply_blocked", names, "the review must still be parked")
        self.assertIn("fb_page_never_posted", names)
        note = [a["note"] for a in acts if a["action"] == "fb_page_never_posted"][0]
        self.assertIn("pages_manage_engagement", note)

    def test_a_page_that_has_posted_before_does_not_cry_connection(self):
        # One review Facebook won't take a comment on is a dead end, not a
        # broken connection — this is the case the parking was built for.
        self._pass([{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}])
        E.collect(self.P, [_ans("fb_reply", status="replied", story="s1")], self.cl, dry=False)
        self._pass([{"open_graph_story": {"id": "s9"}, "recommendation_type": "positive"}])
        acts = E.collect(self.P, [_ans("fb_reply", status="error",
                                       error="(#200) Permissions error", story="s9")],
                         self.cl, dry=False)
        names = [a["action"] for a in acts]
        self.assertIn("fb_reply_blocked", names)
        self.assertNotIn("fb_page_never_posted", names)

    def test_approved_card_refused_is_not_reposted_every_pass(self):
        self._pass([{"open_graph_story": {"id": "s2"}, "recommendation_type": "negative"}])
        st = self._st(); st["reviews"]["s2"]["posted"] = True; self.P.path("fb_review_replies.json").write_text(json.dumps(st))
        E.collect(self.P, [_ans("fb_reply", status="error", error="(#200) Permissions error", story="s2")],
                  self.cl, dry=False)
        self.assertTrue(self._st()["reviews"]["s2"]["posted"])

    def test_answers_split_away_from_zoho(self):
        from automations.online_presence import eco_reviews
        ours, rest = eco_reviews.split([_ans("fb_reviews", status="ok"),
                                        {"kind": "social_check", "result": {"status": "ok"}}])
        self.assertEqual((len(ours), len(rest)), (1, 1))


if __name__ == "__main__":
    unittest.main()
