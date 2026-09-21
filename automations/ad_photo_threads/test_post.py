"""python -m unittest automations.ad_photo_threads.test_post

A fake Slack client only — nothing here touches the real Slack (see
project_tests-sysmodules-mock-posted-to-real-slack: the client is passed in,
never patched through sys.modules)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.ad_photo_threads import collect, post
from automations.ad_photo_threads.titles import TitleBook


class FakeSlack:
    def __init__(self):
        self.posts, self.uploads, self._n = [], [], 0

    def chat_postMessage(self, **kw):
        self._n += 1
        self.posts.append(kw)
        return {"ok": True, "ts": f"100.{self._n}"}

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        return {"ok": True}


def _rep():
    book = TitleBook(["AT&T Sales Agent ? Arlington TX"] * 3)
    rep = collect.DayReport(day=dt.date(2026, 9, 18), book=book)
    img = {"id": "F1", "mimetype": "image/png"}
    rep.candidates = [
        collect.Candidate("Ana Uno", "AT&T Sales Agent, Arlington, TX", "Alexa",
                          "Qualify", "3 Star", "11280 · Alphalete (Irving)",
                          ad="at&t sales agent arlington tx", images=[img], shared=True),
        collect.Candidate("Bo Dos", "AT&T Sales Agent ? Arlington TX", "Alexa",
                          "Disqualify", "", "11280 · Alphalete (Irving)",
                          ad="at&t sales agent arlington tx", images=[img], shared=True),
        collect.Candidate("Cy Tres", "???", "Alexa", "Qualify", "", "x", ad=None),
    ]
    return rep


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(post, "STATE_PATH", Path(self.tmp.name) / "s.json")
        p.start(); self.addCleanup(p.stop)
        d = mock.patch("automations.sara_down.run._download_image",
                       return_value=(b"\x89PNG", "png"))
        d.start(); self.addCleanup(d.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_thread_one_reply_group_photo_once(self):
        cl = FakeSlack()
        c = post.publish(_rep(), "D1", cl=cl, pilot=True)
        self.assertEqual(c["threads_new"], 1)
        self.assertEqual(c["photos"], 1)            # shared shot deduped
        self.assertIn("[PILOT]", cl.posts[0]["text"])   # intro
        self.assertIn("[PILOT]", cl.posts[1]["text"])   # thread parent
        body = cl.uploads[0]["initial_comment"]
        self.assertIn("✅ Ana Uno · 3⭐ · 11280 · Alexa", body)
        self.assertIn("❌ Bo Dos", body)
        self.assertNotIn("Cy Tres", body)            # unknown ad is never posted

    def test_rerun_same_day_posts_nothing(self):
        post.publish(_rep(), "D1", cl=FakeSlack(), pilot=True)
        cl = FakeSlack()
        c = post.publish(_rep(), "D1", cl=cl, pilot=True)
        self.assertEqual((c["replies"], len(cl.posts), len(cl.uploads)), (0, 0, 0))

    def test_max_ads_limits_threads(self):
        rep = _rep()
        rep.candidates[1].ad = "other ad"
        rep.book.ads.append("other ad")
        cl = FakeSlack()
        c = post.publish(rep, "D1", cl=cl, max_ads=1)
        self.assertEqual(c["threads_new"], 1)

    def test_next_day_reuses_the_thread(self):
        post.publish(_rep(), "D1", cl=FakeSlack())
        rep = _rep(); rep.day = dt.date(2026, 9, 19)
        cl = FakeSlack()
        c = post.publish(rep, "D1", cl=cl)
        self.assertEqual(c["threads_new"], 0)
        self.assertEqual(cl.uploads[0]["thread_ts"], "100.1")


if __name__ == "__main__":
    unittest.main()
