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
        self.posts, self.uploads, self.pins, self._n = [], [], [], 0

    def pins_add(self, **kw):
        self.pins.append(("add", kw["timestamp"]))

    def pins_remove(self, **kw):
        self.pins.append(("remove", kw["timestamp"]))

    def chat_postMessage(self, **kw):
        self._n += 1
        self.posts.append(kw)
        return {"ok": True, "ts": f"100.{self._n}"}

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        return {"ok": True}

    def chat_update(self, **kw):
        self.updates = getattr(self, "updates", []) + [kw]
        return {"ok": True}


def _rep():
    book = TitleBook(["AT&T Sales Agent ? Arlington TX"] * 3)
    rep = collect.DayReport(day=dt.date(2026, 9, 18), book=book)
    img = {"id": "F1", "mimetype": "image/png"}
    rep.candidates = [
        collect.Candidate("Ana Uno", "AT&T Sales Agent, Arlington, TX", "Alexa",
                          "Qualify", "3 Star", "Alphalete (Irving)",
                          ad="at&t sales agent arlington tx", images=[img], shared=True),
        collect.Candidate("Bo Dos", "AT&T Sales Agent ? Arlington TX", "Alexa",
                          "Disqualify", "", "Alphalete (Irving)",
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
        # No Claude call in tests: by default the cropper finds everybody.
        c = mock.patch("automations.ad_photo_threads.crop.crop_names",
                       side_effect=lambda data, names, fid="", **kw: {n: b"PNG" + n.encode()
                                                                      for n in names})
        self.crop = c.start(); self.addCleanup(c.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_thread_one_reply_group_photo_once(self):
        cl = FakeSlack()
        c = post.publish(_rep(), "D1", cl=cl, pilot=True)
        self.assertEqual(c["threads_new"], 1)
        self.assertEqual(c["photos"], 2)            # one shot, one tile each
        self.assertIn("[PILOT]", cl.posts[0]["text"])   # intro
        self.assertIn("[PILOT]", cl.posts[1]["text"])   # thread parent
        body = cl.uploads[0]["initial_comment"]
        self.assertIn("ALPHALETE MARKETING, INC. - 11280\n2 total candidates", body)
        self.assertIn("✅ Ana Uno · 3⭐ · Alexa", body)
        self.assertIn("❌ Bo Dos", body)
        self.assertNotIn("group call", body)         # note retired 9/21
        self.assertNotIn("No photo", body)
        self.assertNotIn("Cy Tres", body)            # unknown ad is never posted
        # header = bold title, then edited in place with the week's numbers
        self.assertEqual(cl.posts[1]["text"],
                         ":test_tube: *[PILOT]* *AT&T Sales Agent – Arlington TX*")
        self.assertEqual(cl.updates[-1]["text"], ":test_tube: *[PILOT]* "
                         "*AT&T Sales Agent – Arlington TX - 50% Removed / Avg 3⭐*")

    def test_cropped_shot_posts_one_tile_per_person_no_group_note(self):
        self.crop.side_effect = lambda data, names, fid="", **kw: {n: b"PNG" + n.encode()
                                                                    for n in names}
        cl = FakeSlack()
        post.publish(_rep(), "D1", cl=cl)
        up = cl.uploads[0]
        self.assertEqual(len(up["file_uploads"]), 2)  # Ana's tile + Bo's tile
        self.assertNotIn("group call", up["initial_comment"])
        self.assertEqual(self.crop.call_args[0][1], ["Ana Uno", "Bo Dos"])

    def test_name_not_found_posts_no_photo_and_says_so(self):
        self.crop.side_effect = lambda data, names, fid="", **kw: {
            n: (b"" if n == "Bo Dos" else b"PNG") for n in names}
        cl = FakeSlack()
        c = post.publish(_rep(), "D1", cl=cl)
        self.assertEqual(c["photos"], 1)                     # Ana's tile only
        self.assertIn("_No photo: Bo Dos (name not visible on the Zoom)_",
                      cl.uploads[0]["initial_comment"])

    def test_nobody_found_posts_text_only(self):
        self.crop.side_effect = lambda data, names, fid="", **kw: {n: b"" for n in names}
        cl = FakeSlack()
        c = post.publish(_rep(), "D1", cl=cl)
        self.assertEqual((c["photos"], len(cl.uploads)), (0, 0))
        self.assertIn("No photo: Ana Uno", cl.posts[-1]["text"])

    def test_week_stats_add_up_across_days(self):
        post.publish(_rep(), "D1", cl=FakeSlack())          # Fri: 1 of 2 removed, 3⭐
        rep = _rep(); rep.day = dt.date(2026, 9, 19)
        rep.candidates[0].qualify = "Disqualify"; rep.candidates[1].stars = "1 Star"
        cl = FakeSlack()
        post.publish(rep, "D1", cl=cl)                      # Sat: 2 of 2, 3⭐ + 1⭐
        self.assertIn("75% Removed / Avg 2.3⭐", cl.updates[-1]["text"])

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

    def test_next_day_same_week_reuses_the_thread(self):
        cl = FakeSlack()
        post.publish(_rep(), "D1", cl=cl)
        self.assertEqual(cl.pins, [("add", "100.1")])
        rep = _rep(); rep.day = dt.date(2026, 9, 19)       # Sat, same week
        cl = FakeSlack()
        c = post.publish(rep, "D1", cl=cl)
        self.assertEqual(c["threads_new"], 0)
        self.assertEqual(cl.uploads[0]["thread_ts"], "100.1")
        self.assertEqual(cl.pins, [])

    def test_new_week_fresh_pinned_thread_and_old_one_unpinned(self):
        post.publish(_rep(), "D1", cl=FakeSlack())          # Fri 9/18 -> 100.1
        rep = _rep(); rep.day = dt.date(2026, 9, 21)       # next Monday
        cl = FakeSlack()
        c = post.publish(rep, "D1", cl=cl)
        self.assertEqual(c["threads_new"], 1)
        self.assertEqual(cl.pins, [("add", "100.1"), ("remove", "100.1")])
        # new thread "100.1" in this fake = the fresh one; old ts was also 100.1
        # in its own fake, so check the state instead:
        st = post._load_state()["D1"]["weeks"]
        self.assertFalse(st["2026-09-14"]["at&t sales agent arlington tx"]["pinned"])
        self.assertTrue(st["2026-09-21"]["at&t sales agent arlington tx"]["pinned"])

    def test_pin_refused_still_posts_photos(self):
        cl = FakeSlack()
        def boom(**kw):
            raise RuntimeError("missing_scope pins:write")
        cl.pins_add = boom
        c = post.publish(_rep(), "D1", cl=cl)
        self.assertEqual((c["pin_errors"], c["photos"]), (1, 2))

    def test_pin_reminder_lists_new_then_last_weeks(self):
        refused = FakeSlack()
        refused.pins_add = lambda **kw: (_ for _ in ()).throw(RuntimeError("missing_scope"))
        c1 = post.publish(_rep(), "C1", cl=refused)                 # Fri 9/18
        self.assertEqual(c1["to_pin"], [("AT&T Sales Agent – Arlington TX", "100.1")])
        self.assertEqual(c1["to_unpin"], [])
        rep = _rep(); rep.day = dt.date(2026, 9, 19)               # same week
        self.assertEqual(post.publish(rep, "C1", cl=refused)["to_pin"], [])  # once only
        rep = _rep(); rep.day = dt.date(2026, 9, 21)               # next Monday
        nxt = FakeSlack(); nxt.pins_add = refused.pins_add; nxt._n = 5
        c3 = post.publish(rep, "C1", cl=nxt)
        self.assertEqual([t for _, t in c3["to_pin"]], ["100.6"])
        self.assertEqual([t for _, t in c3["to_unpin"]], ["100.1"])
        txt = post.pin_reminder_text("C1", rep.day, c3["to_pin"], c3["to_unpin"])
        self.assertIn("archives/C1/p1006|", txt)
        self.assertIn("Unpin last week's", txt)

    def test_no_reminder_when_lucy_can_pin(self):
        c = post.publish(_rep(), "C1", cl=FakeSlack())
        self.assertEqual((c["to_pin"], c["to_unpin"]), ([], []))
        self.assertFalse(post.send_pin_reminder("C1", dt.date(2026, 9, 18), c))

    def test_retire_channel_deletes_only_lucys_posts(self):
        post.publish(_rep(), "C1", cl=FakeSlack())
        cl = FakeSlack()
        cl.auth_test = lambda: {"user_id": "ULUCY"}
        cl.conversations_replies = lambda **kw: {"messages": [
            {"ts": "100.1", "user": "ULUCY"},
            {"ts": "100.2", "user": "ULUCY", "files": [{"id": "F9"}]},
            {"ts": "100.3", "user": "URAF"}]}
        gone, files = [], []
        cl.chat_delete = lambda **kw: gone.append(kw["ts"])
        cl.files_delete = lambda **kw: files.append(kw["file"])
        c = post.retire_channel("C1", cl=cl)
        self.assertEqual(gone, ["100.2", "100.1"])           # replies, then header
        self.assertEqual(files, ["F9"])
        self.assertEqual(c["kept_others"], 1)
        self.assertNotIn("C1", post._load_state())

    def test_forget_channel_lets_a_preview_repost(self):
        post.publish(_rep(), "D1", cl=FakeSlack(), pilot=True)
        post.forget_channel("D1")
        c = post.publish(_rep(), "D1", cl=FakeSlack(), pilot=True)
        self.assertEqual((c["threads_new"], c["replies"]), (1, 1))

    def test_add_photo_replies_in_the_existing_thread(self):
        post.publish(_rep(), "C1", cl=FakeSlack())
        cl = FakeSlack()
        out = post.add_photos(_rep(), "C1", ["ana uno", "Nobody"], cl=cl)
        self.assertEqual(out["ana uno"], "added 1 photo(s)")
        self.assertIn("not on the sheet", out["Nobody"])
        self.assertEqual(cl.uploads[0]["thread_ts"], "100.1")
        self.assertIn("photo added\n✅ Ana Uno · 3⭐ · Alexa", cl.uploads[0]["initial_comment"])

    def test_day_done_marker(self):
        d = dt.date(2026, 9, 18)
        self.assertFalse(post.day_done("D1", d))
        post.mark_day_done("D1", d)
        self.assertTrue(post.day_done("D1", d))
        self.assertFalse(post.day_done("C9", d))


if __name__ == "__main__":
    unittest.main()
