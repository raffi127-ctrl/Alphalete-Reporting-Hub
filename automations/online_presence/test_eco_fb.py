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
        self.assertEqual(self.queued, [], "replies wait in the outbox")
        E.send_next(self.P, live=True)
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
        # It must point at the REPLY PATH (the browser sign-in), not at the
        # token scope. Blaming pages_manage_engagement was my wrong guess:
        # Graph never lets a Page comment on a person's review whatever the
        # scopes, which fb4c8ae established and routed to the browser.
        self.assertIn("fb_signin", note)
        self.assertNotIn("pages_manage_engagement", note)

    def test_a_page_with_history_is_not_called_never_posted(self):
        # The cold start that would have cried wolf: `ever_posted` begins at 0
        # at the version that introduced it, so a page whose replies landed
        # BEFORE then must still read as having posted. raf's did, twice, on
        # 11/15 -- the very office this warning exists for.
        self._pass([{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}])
        st = self._st()
        st.pop("ever_posted", None)
        st["reviews"]["s1"] = {"posted": True}        # landed, not blocked
        self.P.path("fb_review_replies.json").write_text(json.dumps(st))
        self.assertTrue(E._ever_posted(self._st()))

    def test_a_parked_review_does_not_count_as_having_posted(self):
        self.assertFalse(E._ever_posted(
            {"reviews": {"s1": {"posted": True, "blocked": "Permissions error"}}}))

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

    # ---- 11/16: a review by a person is typed on facebook.com, one at a time ----
    def _two_thank_yous(self):
        self._pass([{"open_graph_story": {"id": "a"}, "recommendation_type": "positive"},
                    {"open_graph_story": {"id": "b"}, "recommendation_type": "positive"}])

    def test_one_reply_in_flight_and_spaced_out(self):
        self._two_thank_yous()
        E.send_next(self.P, live=True, now=1e9)
        self.assertIsNone(E.send_next(self.P, live=True, now=1e9 + 60), "two in flight")
        E.collect(self.P, [_ans("fb_reply", status="replied", via="browser", story="a")], self.cl, dry=False)
        self.assertIsNone(E.send_next(self.P, live=True, now=1e9 + 100), "sent before the gap")
        E.send_next(self.P, live=True, now=1e9 + E.OUTBOX_GAP_MIN * 60 + 1)
        self.assertEqual([q[1]["story"] for q in self.queued], ["a", "b"])

    def test_security_check_holds_everything_and_dms_the_owner_once(self):
        self.P = __import__("dataclasses").replace(self.P, owner_slack_id="UOWN")
        self._two_thank_yous()
        E.send_next(self.P, live=True, now=1e9)
        acts = E.collect(self.P, [_ans("fb_reply", status="checkpoint", story="a")], self.cl, dry=False)
        self.assertIn("dm_owner", [x["action"] for x in acts])
        self.assertEqual(self.cl.posts[-1]["channel"], "UOWN")
        later = 1e9 + E.OUTBOX_GAP_MIN * 60 + 1
        self.assertEqual(E.send_next(self.P, live=True, now=later)["action"], "fb_replies_on_hold")
        self.assertEqual(len(self.queued), 1, "nothing sent while Facebook wants a check")
        self.assertEqual(E._load(self.P)["outbox"][0]["story"], "a", "the held reply kept its place")
        E.collect(self.P, [_ans("fb_reply", status="checkpoint", story="a")], self.cl, dry=False)
        self.assertEqual(len(self.cl.posts), 1, "one DM a day")

    def test_signing_in_releases_the_hold_and_unparks_refused_reviews(self):
        self._pass([{"open_graph_story": {"id": "s1"}, "recommendation_type": "positive"}])
        E.collect(self.P, [_ans("fb_reply", status="error", error="(#200) Permissions error", story="s1")],
                  self.cl, dry=False)
        st = E._load(self.P); st["paused"] = {"why": "needs_signin", "at": 1}; E._save(self.P, st)
        acts = E.collect(self.P, [_ans("fb_signin", status="signed_in")], self.cl, dry=False)
        self.assertEqual(acts[0]["action"], "facebook_signed_in")
        self.assertNotIn("paused", E._load(self.P))
        self.assertNotIn("s1", self._st()["reviews"], "a refused review comes back to be answered")

    def test_one_signed_out_reply_holds_quietly_until_the_next_read(self):
        # Raf 11/17: a reply said "signed out" 10 min after a read got in fine.
        acts = E.collect(self.P, [_ans("fb_reply", status="needs_signin", story="s9")], self.cl, dry=False)
        self.assertEqual(self.cl.posts, [], "no DM on one reply's word")
        self.assertEqual(E._load(self.P)["paused"]["why"], "needs_signin")
        acts = E.collect(self.P, [_ans("fb_reviews", status="ok", reviews=[])], self.cl, dry=False)
        self.assertIn("fb_signin_false_alarm", [a["action"] for a in acts])
        self.assertNotIn("paused", E._load(self.P))
        self.assertEqual(self.cl.posts, [])

    def test_the_next_read_signed_out_too_tells_the_owner(self):
        P = offices.Presence(key="kash", business_name="Kash", slack_channel="C1", approvers=("U1",),
                             facebook_page_id="9", reviews_via="eco", owner_slack_id="UOWNER")
        E.collect(P, [_ans("fb_reply", status="needs_signin", story="s9")], self.cl, dry=False)
        E.collect(P, [_ans("fb_reviews", status="signed_out", error="Facebook signed out")], self.cl, dry=False)
        self.assertEqual([p["channel"] for p in self.cl.posts], ["UOWNER"])
        self.assertEqual(E._load(P)["paused"]["why"], "needs_signin")

    def test_a_checkpoint_still_tells_the_owner_at_once(self):
        P = offices.Presence(key="kash", business_name="Kash", slack_channel="C1", approvers=("U1",),
                             facebook_page_id="9", reviews_via="eco", owner_slack_id="UOWNER")
        E.collect(P, [_ans("fb_reply", status="checkpoint", story="s9")], self.cl, dry=False)
        self.assertEqual(len(self.cl.posts), 1)

    def test_signing_in_keeps_an_approved_card_and_its_check_mark(self):
        # Megan 11/16: "I already approved these responses as they were posted before".
        self._pass([{"open_graph_story": {"id": "s2"}, "recommendation_type": "negative"}])
        st = self._st(); st["reviews"]["s2"]["posted"] = True
        self.P.path("fb_review_replies.json").write_text(json.dumps(st))
        E.collect(self.P, [_ans("fb_reply", status="error", error="(#200) Permissions error", story="s2")],
                  self.cl, dry=False)
        card = self._st()["reviews"]["s2"]["card_ts"]
        E.collect(self.P, [_ans("fb_signin", status="signed_in")], self.cl, dry=False)
        kept = self._st()["reviews"]["s2"]
        self.assertEqual(kept["card_ts"], card, "same card, so its ✅ still counts")
        self.assertFalse(kept["posted"])
        self.assertNotIn("blocked", kept)

    def test_cant_comment_as_page_comes_back_a_day_later_with_its_card(self):
        self._pass([{"open_graph_story": {"id": "s2"}, "recommendation_type": "negative"}])
        E.collect(self.P, [_ans("fb_reply", status="not_page", error="this Facebook sign-in can't comment as X",
                                story="s2")], self.cl, dry=False)
        card = self._st()["reviews"]["s2"]["card_ts"]
        self.assertTrue(self._st()["reviews"]["s2"]["blocked"])
        fb = self._st()
        self.assertEqual(E._retry_not_page(fb, __import__("time").time() + 3600), 0, "not within the day")
        self.assertEqual(E._retry_not_page(fb, __import__("time").time() + E.NOT_PAGE_RETRY_HOURS * 3600 + 5), 1)
        self.assertEqual(fb["reviews"]["s2"]["card_ts"], card)
        self.assertFalse(fb["reviews"]["s2"]["posted"])
        self.assertNotIn("blocked", fb["reviews"]["s2"])

    def test_cant_comment_as_page_parked_before_the_stamp_retries_within_hours(self):
        fb = {"reviews": {"s": {"posted": True, "card_ts": "1",
                                "blocked": "this Facebook sign-in can't comment as Alphalete Marketing"}}}
        t = 1e9
        self.assertEqual(E._retry_not_page(fb, t), 0)
        self.assertEqual(E._retry_not_page(fb, t + 3601), 1)

    def test_cant_comment_as_page_parks_it(self):
        self._two_thank_yous()
        E.send_next(self.P, live=True, now=1e9)
        E.collect(self.P, [_ans("fb_reply", status="not_page", error="x", story="a")], self.cl, dry=False)
        self.assertTrue(self._st()["reviews"]["a"]["blocked"])

    def test_facebook_alone_can_be_on_the_office_computer(self):
        from dataclasses import replace
        self.assertTrue(E.is_eco(replace(self.P, reviews_via="lucy", facebook_via="eco")))
        self.assertFalse(E.is_eco(replace(self.P, reviews_via="lucy", facebook_via="lucy")))

    def test_answers_split_away_from_zoho(self):
        from automations.online_presence import eco_reviews
        ours, rest = eco_reviews.split([_ans("fb_reviews", status="ok"),
                                        {"kind": "social_check", "result": {"status": "ok"}}])
        self.assertEqual((len(ours), len(rest)), (1, 1))


class BrowserOffice(unittest.TestCase):
    """11/17: no Meta key -- the office computer reads + replies on facebook.com."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name)); self.root.start()
        self.P = offices.Presence(key="kash", business_name="Kash", slack_channel="C1", approvers=("U1",),
                                  facebook_url="https://www.facebook.com/kash", facebook_via="browser")
        self.cl, self.queued = FakeSlack(), []
        self.q = mock.patch.object(relay, "enqueue",
                                   side_effect=lambda o, k, pl, live: self.queued.append((k, pl)) or "J")
        self.q.start()

    def tearDown(self):
        self.q.stop(); self.root.stop(); self.tmp.cleanup()

    def test_is_eco_without_a_page_id(self):
        self.assertTrue(E.is_eco(self.P))
        bad = offices.Presence(key="x", business_name="X", slack_channel="C", facebook_via="browser").problems()
        self.assertTrue(any("facebook_url" in p for p in bad))
        self.assertFalse(any("facebook" in p for p in self.P.problems()))

    def test_the_sign_in_is_the_connection(self):
        self.assertFalse(E.connected(self.P))
        E.collect(self.P, [_ans("fb_signin", status="signed_in")], self.cl, dry=False)
        self.assertTrue(E.connected(self.P))

    def test_read_and_reply_carry_the_page(self):
        E.collect(self.P, [_ans("fb_signin", status="signed_in")], self.cl, dry=False)
        E.ensure_read(self.P, live=True)
        self.assertEqual({k: self.queued[-1][1][k] for k in ("do", "via", "page_url", "page_name")},
                         {"do": "fb_reviews", "via": "browser", "page_url": "https://www.facebook.com/kash",
                          "page_name": "Kash"})
        E.collect(self.P, [_ans("fb_reviews", status="ok", via="browser", reviews=[
            {"story": "fan/posts/pfbidA", "recommendation_type": "positive", "review_text": "great"}])],
            self.cl, dry=False)
        with mock.patch.object(RR, "_client", return_value=self.cl), \
             mock.patch.object(RR, "draft_reply", return_value="Thank you!"), \
             mock.patch.object(fb_reviews, "_keys", side_effect=AssertionError("Meta key used")):
            acts = fb_reviews.process(live=True, profile=self.P, reviews=E.reviews(self.P), post=E.poster(self.P))
        self.assertEqual([a["action"] for a in acts], ["auto_post"])
        E.send_next(self.P, live=True)
        self.assertEqual(self.queued[-1], ("social_post", {"do": "fb_reply", "story": "fan/posts/pfbidA",
                                                           "comment": "Thank you!", "page_name": "Kash"}))


class NeverLanded(Base):
    """11/17: nine replies came back "replied" and none was on Facebook."""
    def _posted_thank_you(self):
        E.collect(self.P, [_ans("fb_reviews", status="ok", reviews=[
            {"story": "s1", "recommendation_type": "positive", "review_text": "great"}])], self.cl, dry=False)
        self._pass(E.reviews(self.P))
        E.send_next(self.P, live=True)
        E.collect(self.P, [_ans("fb_reply", status="replied", via="browser", story="s1")], self.cl, dry=False)
        st = self._st(); st["reviews"]["s1"]["replied_at"] = 1   # long ago
        self.P.path("fb_review_replies.json").write_text(json.dumps(st))

    def _st(self):
        return json.loads(self.P.path("fb_review_replies.json").read_text())

    def _read_again(self):
        return E.collect(self.P, [_ans("fb_reviews", status="ok", reviews=[
            {"story": "s1", "recommendation_type": "positive", "review_text": "great"}])], self.cl, dry=False)

    def test_posted_reviews_are_not_skipped_so_a_miss_shows(self):
        self._posted_thank_you()
        E._save(self.P, dict(E._load(self.P), read_at=0, pending_read={}))
        E.ensure_read(self.P, live=True)
        self.assertNotIn("s1", self.queued[-1][1]["skip"])

    def test_still_unanswered_goes_back_with_the_same_words(self):
        self._posted_thank_you()
        acts = self._read_again()
        self.assertIn("fb_reply_not_there_resent", [a["action"] for a in acts])
        self.assertEqual(E._load(self.P)["outbox"], [{"story": "s1", "comment": "Thank you!"}])

    def test_a_fresh_reply_is_given_time_to_show(self):
        self._posted_thank_you()
        st = self._st(); st["reviews"]["s1"]["replied_at"] = __import__("time").time()
        self.P.path("fb_review_replies.json").write_text(json.dumps(st))
        self.assertNotIn("fb_reply_not_there_resent", [a["action"] for a in self._read_again()])

    def test_three_misses_park_it_out_loud(self):
        self._posted_thank_you()
        for _ in range(E.RELAND_MAX):
            self._read_again()
            E._save(self.P, dict(E._load(self.P), outbox=[]))
        acts = self._read_again()
        self.assertIn("fb_reply_never_landed", [a["action"] for a in acts])
        self.assertTrue(self._st()["reviews"]["s1"]["blocked"])


if __name__ == "__main__":
    unittest.main()
