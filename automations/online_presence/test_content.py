"""Monthly blog + quarterly press release drafts: timing, one per period, ✅/❌/💀.

    python -m unittest automations.online_presence.test_content

Claude, Google and Slack are faked.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.online_presence import content as C, offices


class FakeSlack:
    def __init__(self):
        self.posts, self.files, self.rx = [], [], {}

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "7.%d" % len(self.posts)}

    def files_upload_v2(self, **kw):
        self.files.append(kw)

    def conversations_replies(self, channel, ts):
        return {"messages": [{"ts": t, "reactions": r} for t, r in self.rx.items()]}


class When(unittest.TestCase):
    def test_blog_first_weekday_from_10am(self):
        self.assertIsNone(C.due("blog", dt.datetime(2026, 11, 2, 9)))        # Mon 9am
        self.assertEqual(C.due("blog", dt.datetime(2026, 11, 2, 10)), "blog-2026-11")
        self.assertIsNone(C.due("blog", dt.datetime(2026, 11, 1, 12)))       # Sunday the 1st

    def test_press_only_quarter_months(self):
        self.assertIsNone(C.due("press", dt.datetime(2026, 11, 2, 11)))
        self.assertEqual(C.due("press", dt.datetime(2026, 10, 1, 11)), "press-2026-Q4")

    def test_rules_carry_the_compliance_lines(self):
        for w in ("age", "gender", "team members", "MLM", "first names only"):
            self.assertIn(w, C.RULES)


class Flow(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 2, 11)       # first weekday of Nov, not a quarter month

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        self.p = offices.Presence(key="kash", business_name="Kash Marketing",
                                  slack_channel="C0KASHROOM", approvers=("U046XBPN0G2",),
                                  mode="live")
        self.n = 0

        def fake_draft(P, kind, src, feedback=""):
            self.n += 1
            return {"title": f"T{self.n}", "body": f"body {self.n} {feedback}"}
        self.patches = [mock.patch.object(C, "draft", side_effect=fake_draft),
                        mock.patch.object(C, "material", return_value="stuff")]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.root.stop()
        self.tmp.cleanup()

    def _react(self, cl, ts, name, user="U046XBPN0G2"):
        cl.rx[ts] = [{"name": name, "users": [user]}]

    def test_one_blog_a_month_no_press_in_november(self):
        cl = FakeSlack()
        acts = C.step(self.p, cl, live=True, now=self.NOW)
        self.assertEqual([a["action"] for a in acts], ["propose_blog", ])
        self.assertEqual(len(cl.files), 1)
        C.step(self.p, cl, live=True, now=self.NOW)
        self.assertEqual(len(cl.files), 1)                       # not a second one

    def test_approve_posts_the_final(self):
        cl = FakeSlack()
        C.step(self.p, cl, live=True, now=self.NOW)
        self._react(cl, "7.2", "white_check_mark")               # the draft message
        acts = C.step(self.p, cl, live=True, now=self.NOW)
        self.assertEqual(acts[0]["action"], "blog_approved")
        self.assertTrue(cl.files[-1]["title"].startswith("FINAL"))
        self.assertEqual(C.step(self.p, cl, live=True, now=self.NOW), [])

    def test_x_redrafts_once_with_the_note(self):
        cl = FakeSlack()
        C.step(self.p, cl, live=True, now=self.NOW)
        self._react(cl, "7.2", "x")
        with mock.patch("automations.brand_audit.social_inbox._human_reply_after",
                        return_value={"text": "shorter"}):
            acts = C.step(self.p, cl, live=True, now=self.NOW)
            self.assertEqual(acts[0]["action"], "blog_redraft")
            self.assertIn("shorter", cl.posts[-1]["text"])
            n = len(cl.files)
            C.step(self.p, cl, live=True, now=self.NOW)           # old ❌ is on the old draft
            self.assertEqual(len(cl.files), n)

    def test_a_reps_check_does_nothing(self):
        cl = FakeSlack()
        C.step(self.p, cl, live=True, now=self.NOW)
        self._react(cl, "7.2", "white_check_mark", user="UREP0001")
        self.assertEqual(C.step(self.p, cl, live=True, now=self.NOW), [])

    def test_skull_skips(self):
        cl = FakeSlack()
        C.step(self.p, cl, live=True, now=self.NOW)
        self._react(cl, "7.1", "skull")
        self.assertEqual(C.step(self.p, cl, live=True, now=self.NOW)[0]["action"], "blog_skipped")

    def test_dry_posts_nothing(self):
        cl = FakeSlack()
        acts = C.step(self.p, cl, live=False, now=self.NOW)
        self.assertEqual(acts[0]["action"], "would_propose_blog")
        self.assertEqual((cl.posts, cl.files), ([], []))


if __name__ == "__main__":
    unittest.main()
