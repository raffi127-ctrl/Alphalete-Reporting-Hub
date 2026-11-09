"""The weekly reel: Thursday proposal, ✅/❌/💀 on the caption, queued once.

    python -m unittest automations.online_presence.test_reels_flow

Slack, the video maker, Claude and the relay are faked.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.online_presence import offices, reels_flow as R

THU = dt.datetime(2026, 11, 12, 11, 0)       # a Thursday, 11am
WED = dt.datetime(2026, 11, 11, 11, 0)


class FakeSlack:
    def __init__(self):
        self.posts, self.files, self.rx = [], [], {}

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "5.%d" % len(self.posts)}

    def files_upload_v2(self, **kw):
        self.files.append(kw)

    def conversations_replies(self, channel, ts):
        return {"messages": [{"ts": t, "reactions": r} for t, r in self.rx.items()]}


def react(cl, ts, name, user="U046XBPN0G2"):
    cl.rx[ts] = [{"name": name, "users": [user]}]


class Weekly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        self.p = offices.Presence(key="kash", business_name="Kash Marketing",
                                  slack_channel="C0KASHROOM", approvers=("U046XBPN0G2",),
                                  pages=("instagram",), mode="live")
        self.photos = []
        for i in range(4):
            f = Path(self.tmp.name) / f"p{i}.jpg"
            f.write_bytes(b"jpg")
            self.photos.append(f)
        self.patches = [
            mock.patch.object(R, "week_photos", side_effect=lambda P, now: self.photos),
            mock.patch.object(R, "_caption", side_effect=lambda P, ph, n, feedback="", avoid=None:
                              f"caption {len(avoid or [])}"),
            mock.patch("automations.brand_audit.reels.make_reel", side_effect=lambda ps, out: out),
        ]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.root.stop()
        self.tmp.cleanup()

    def test_only_on_thursday(self):
        cl = FakeSlack()
        self.assertEqual(R.step(self.p, cl, live=True, now=WED), [])
        self.assertEqual(cl.posts, [])

    def test_proposed_once_with_video_and_caption_in_thread(self):
        cl = FakeSlack()
        acts = R.step(self.p, cl, live=True, now=THU)
        self.assertEqual(acts[0]["action"], "propose_reel")
        self.assertNotIn("thread_ts", cl.posts[0])                 # header
        self.assertEqual(cl.files[0]["thread_ts"], "5.1")          # video in thread
        self.assertIn("caption 0", cl.posts[1]["text"])
        acts2 = R.step(self.p, cl, live=True, now=THU)             # no second reel
        self.assertEqual(acts2[0]["action"], "reel_awaiting_approval")
        self.assertEqual(len(cl.files), 1)

    def test_too_few_photos_no_reel(self):
        self.photos = self.photos[:2]
        cl = FakeSlack()
        self.assertEqual(R.step(self.p, cl, live=True, now=THU)[0]["action"], "no_reel")
        self.assertEqual(cl.posts, [])

    def test_check_queues_the_video_once(self):
        cl = FakeSlack()
        R.step(self.p, cl, live=True, now=THU)
        react(cl, "5.2", "white_check_mark")                       # on the caption
        with mock.patch("automations.online_presence.relay.enqueue_post",
                        return_value="JOB9") as q:
            acts = R.step(self.p, cl, live=True, now=THU)
            again = R.step(self.p, cl, live=True, now=THU)
        self.assertEqual(acts[0]["action"], "reel_queue_to_office")
        self.assertEqual(q.call_count, 1)
        self.assertEqual(q.call_args.kwargs["media"], "video")
        self.assertEqual(again, [])

    def test_x_gives_one_new_caption_not_one_per_pass(self):
        cl = FakeSlack()
        R.step(self.p, cl, live=True, now=THU)
        react(cl, "5.2", "x")
        acts = R.step(self.p, cl, live=True, now=THU)
        self.assertEqual(acts[0]["action"], "reel_new_caption")
        n = len(cl.posts)
        R.step(self.p, cl, live=True, now=THU)                     # old ❌ is on the OLD caption
        self.assertEqual(len(cl.posts), n)

    def test_a_reps_check_does_not_post(self):
        cl = FakeSlack()
        R.step(self.p, cl, live=True, now=THU)
        react(cl, "5.2", "white_check_mark", user="UREP0001")
        with mock.patch("automations.online_presence.relay.enqueue_post",
                        side_effect=AssertionError("queued")):
            self.assertEqual(R.step(self.p, cl, live=True, now=THU)[0]["action"],
                             "reel_awaiting_approval")

    def test_skull_skips_the_week(self):
        cl = FakeSlack()
        R.step(self.p, cl, live=True, now=THU)
        react(cl, "5.1", "skull")
        self.assertEqual(R.step(self.p, cl, live=True, now=THU)[0]["action"], "reel_skipped")
        self.assertEqual(R.step(self.p, cl, live=True, now=THU), [])

    def test_dry_makes_and_posts_nothing(self):
        cl = FakeSlack()
        with mock.patch("automations.brand_audit.reels.make_reel",
                        side_effect=AssertionError("rendered")):
            acts = R.step(self.p, cl, live=False, now=THU)
        self.assertEqual(acts[0]["action"], "would_propose_reel")
        self.assertEqual((cl.posts, cl.files), ([], []))


class ReelAnswers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        self.p = offices.Presence(key="kash", business_name="Kash Marketing",
                                  slack_channel="C0KASHROOM", owner_slack_id="U046XBPN0G2",
                                  pages=("instagram",), mode="live")
        R._save(self.p.path("reels.json"),
                {"2026-W46": {"status": "queued", "ts": "5.1", "eco_job": "RJ1"}})

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def _answer(self, result):
        from automations.online_presence import watch
        cl = FakeSlack()
        cl.reactions_add = lambda **kw: cl.posts.append(("react", kw))
        acts = watch.collect(self.p, [{"job_id": "RJ1", "kind": "social_post",
                                       "answered": True, "result": result}], cl, dry=False)
        return acts, cl, R._load(self.p.path("reels.json"))["2026-W46"]

    def test_posted_rockets_the_reel_thread(self):
        acts, cl, reel = self._answer({"status": "posted", "channels": ["instagram"]})
        self.assertEqual(reel["status"], "posted")
        self.assertEqual(cl.posts[0]["thread_ts"], "5.1")

    def test_signed_out_waits_a_day_then_retries(self):
        acts, cl, reel = self._answer({"status": "signed_out", "channels": []})
        self.assertEqual(reel["status"], "blocked")
        self.assertNotIn("eco_job", reel)
        nxt = dt.datetime.fromisoformat(reel["blocked_day"]) + dt.timedelta(days=1, hours=11)
        with mock.patch.object(R, "_caption", return_value="c"):
            R.step(self.p, FakeSlack(), live=True, now=nxt.replace(tzinfo=None))
        week = R.week_key(nxt)
        # a later day in the SAME week flips it back to proposed (✅ still there)
        if week == "2026-W46":
            self.assertEqual(R._load(self.p.path("reels.json"))["2026-W46"]["status"],
                             "proposed")


class OfficeComputerPostsVideo(unittest.TestCase):
    def test_video_job_posts_as_video(self):
        import base64
        from automations.icd_alerts import social_post as SP
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(SP, "PROFILE", Path(d)), \
                mock.patch("automations.brand_audit.zoho_draft.post_now",
                           return_value={"ok": True, "channels": ["instagram"]}) as pn:
            SP.post({"caption": "c", "media": "video", "pages": ["instagram"],
                     "photo_b64": base64.b64encode(b"mp4").decode()}, True)
        self.assertEqual(pn.call_args.kwargs["media_type"], "video")
        self.assertTrue(pn.call_args.args[1].endswith(".mp4"))


if __name__ == "__main__":
    unittest.main()
