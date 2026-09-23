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
from automations.ad_photo_threads.titles import TitleBook, norm


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
        # These tests pin down the weekly threads (9/21-9/23); the forever
        # threads Raf asked for 9/23 are ForeverThreadTests below.
        w = mock.patch.object(post.config, "ONE_THREAD_PER_AD", False)
        w.start(); self.addCleanup(w.stop)

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

    def test_no_screenshot_is_watched_and_added_when_it_shows_up(self):
        rep = _rep()
        rep.candidates[1].images = []; rep.candidates[1].shared = False
        post.publish(rep, "C1", cl=FakeSlack())                 # Fri 9/18
        self.assertEqual(post._load_state()["C1"]["late"], {"2026-09-18": ["Bo Dos"]})
        # Saturday: the interviewer has since posted Bo's shot.
        cl = FakeSlack()
        out = post.retry_late("C1", dt.date(2026, 9, 19), build=lambda d: _rep(), cl=cl)
        self.assertEqual(out, {"2026-09-18 Bo Dos": "added 1 photo(s)"})
        self.assertEqual(cl.uploads[0]["thread_ts"], "100.1")
        self.assertEqual(post._load_state()["C1"]["late"], {})

    def test_watch_by_hand(self):
        self.assertEqual(post.watch("C1", dt.date(2026, 9, 21), ["Chris F"]), ["Chris F"])
        self.assertEqual(post._load_state()["C1"]["late"], {"2026-09-21": ["Chris F"]})

    def test_late_watch_gives_up_after_three_days(self):
        rep = _rep()
        rep.candidates[1].images = []
        post.publish(rep, "C1", cl=FakeSlack())
        out = post.retry_late("C1", dt.date(2026, 9, 22),
                              build=lambda d: self.fail("should not rebuild"))
        self.assertEqual(out, {})
        self.assertEqual(post._load_state()["C1"]["late"], {})

    def test_description_goes_under_each_candidate(self):
        rep = _rep()
        rep.candidates[0].notes = ["Dallas, retail, can start asap"]
        cl = FakeSlack()
        post.publish(rep, "C1", cl=cl)
        body = cl.uploads[0]["initial_comment"]
        lines = body.splitlines()
        i = next(n for n, ln in enumerate(lines) if "Ana Uno" in ln)
        self.assertEqual(lines[i + 1], "> Dallas, retail, can start asap")

    def test_add_notes_edits_the_posted_reply_in_place(self):
        rep = _rep()
        cl = FakeSlack()
        post.publish(rep, "C1", cl=cl)
        posted = cl.uploads[0]["initial_comment"] + "\n_No photo: Bo Dos (name not visible on the Zoom)_"
        thread = post._load_state()["C1"]["weeks"]["2026-09-14"]["at&t sales agent arlington tx"]["thread_ts"]
        cl.auth_test = lambda: {"user_id": "ULUCY"}
        cl.conversations_replies = lambda **kw: {"messages": [
            {"ts": thread, "user": "ULUCY", "text": "*AT&T Sales Agent*"},
            {"ts": "200.1", "user": "UOTHER", "text": "*Fri 9/18*\nnot ours"},
            {"ts": "200.2", "user": "ULUCY", "text": posted}]}
        cl.updates = []
        rep.candidates[1].notes = ["declined, commute"]
        got = post.add_notes(rep, "C1", cl=cl)
        self.assertEqual(len(cl.updates), 1)
        self.assertEqual(cl.updates[0]["ts"], "200.2")
        self.assertIn("> declined, commute", cl.updates[0]["text"])
        self.assertIn("_No photo: Bo Dos", cl.updates[0]["text"])   # kept
        self.assertEqual(len(cl.uploads), 1)                     # nothing new posted
        self.assertIn("edited", list(got.values())[0])
        cl.updates = []
        post.add_notes(rep, "C1", cl=cl, dry_run=True)
        self.assertEqual(cl.updates, [])

    def test_merge_dups_moves_candidates_and_deletes_the_duplicate(self):
        # 9/22: "AT&T Services (Spanish Required) ? Dallas TX" = the Client
        # Solutions Specialist Dallas ad without its first words.
        full = "Client Solutions Specialist - AT&T Services (Spanish Required), Dallas, TX"
        short = "AT&T Services (Spanish Required) ? Dallas TX"
        img = {"id": "F1", "mimetype": "image/png"}

        def rep_with(ad_of_short):
            rep = collect.DayReport(day=dt.date(2026, 9, 22),
                                    book=TitleBook([full] * 5 + [short] * 3))
            rep.candidates = [
                collect.Candidate("Ana Uno", full, "Alexa", "Qualify", "3 Star",
                                  "Alphalete (Irving)", ad=norm(full), images=[img]),
                collect.Candidate("Bo Dos", short, "Alexa", "Disqualify", "4 Star",
                                  "Alphalete (Irving)", ad=ad_of_short, images=[img]),
            ]
            return rep

        # What went out before the fix: two threads for one ad.
        post.publish(rep_with(norm(short)), "C1", cl=FakeSlack())
        wk = post._load_state()["C1"]["weeks"]["2026-09-21"]
        self.assertEqual(len(wk), 2)
        real_ts, dup_ts = wk[norm(full)]["thread_ts"], wk[norm(short)]["thread_ts"]

        cl = FakeSlack()
        cl.auth_test = lambda: {"user_id": "ULUCY"}
        cl.conversations_replies = lambda **kw: {"messages": [
            {"ts": dup_ts, "user": "ULUCY"}, {"ts": "9.9", "user": "ULUCY"}]}
        gone = []
        cl.chat_delete = lambda **kw: gone.append(kw["ts"])
        cl.files_delete = lambda **kw: None
        fixed = rep_with(norm(full))
        self.assertIn("would move 1", list(post.merge_dups(
            "C1", fixed.day, build=lambda d: fixed, cl=cl, dry_run=True).values())[0])
        self.assertEqual((cl.uploads, gone), ([], []))

        got = post.merge_dups("C1", fixed.day, build=lambda d: fixed, cl=cl)
        self.assertIn("moved 1", list(got.values())[0])
        self.assertEqual(len(cl.uploads), 1)                     # Bo only, in the real thread
        self.assertEqual(cl.uploads[0]["thread_ts"], real_ts)
        self.assertIn("Bo Dos", cl.uploads[0]["initial_comment"])
        self.assertNotIn("Ana Uno", cl.uploads[0]["initial_comment"])
        self.assertEqual(gone, ["9.9", dup_ts])                  # duplicate gone
        wk = post._load_state()["C1"]["weeks"]["2026-09-21"]
        self.assertEqual(list(wk), [norm(full)])
        self.assertEqual(wk[norm(full)]["stats"]["2026-09-22"]["n"], 2)
        self.assertIn("50% Removed", cl.updates[-1]["text"])      # header redone
        # Run again: nothing left to merge, nothing posted.
        self.assertEqual(post.merge_dups("C1", fixed.day, build=lambda d: fixed, cl=cl), {})
        self.assertEqual(len(cl.uploads), 1)

    def test_day_done_marker(self):
        d = dt.date(2026, 9, 18)
        self.assertFalse(post.day_done("D1", d))
        post.mark_day_done("D1", d)
        self.assertTrue(post.day_done("D1", d))
        self.assertFalse(post.day_done("C9", d))


if __name__ == "__main__":
    unittest.main()


class ForeverThreadTests(PublishTests):
    """Raf 2026-09-23: one thread per ad forever, a new one only for a new ad."""
    def setUp(self):
        super().setUp()
        f = mock.patch.object(post.config, "ONE_THREAD_PER_AD", True)
        f.start(); self.addCleanup(f.stop)

    # The weekly-only behaviour doesn't apply here.
    test_new_week_fresh_pinned_thread_and_old_one_unpinned = None
    test_pin_reminder_lists_new_then_last_weeks = None
    test_add_notes_edits_the_posted_reply_in_place = None
    test_merge_dups_moves_candidates_and_deletes_the_duplicate = None
    test_one_thread_one_reply_group_photo_once = None

    def test_next_week_reuses_the_same_thread_and_keeps_the_pin(self):
        post.publish(_rep(), "D1", cl=FakeSlack())          # Fri 9/18 -> 100.1
        rep = _rep(); rep.day = dt.date(2026, 9, 21)       # next Monday
        cl = FakeSlack(); cl._n = 7
        c = post.publish(rep, "D1", cl=cl)
        self.assertEqual(c["threads_new"], 0)
        self.assertEqual(cl.uploads[0]["thread_ts"], "100.1")
        self.assertEqual(cl.pins, [])                      # nothing unpinned
        ad = post._load_state()["D1"]["weeks"][post.FOREVER]["at&t sales agent arlington tx"]
        self.assertEqual(ad["days"], ["2026-09-18", "2026-09-21"])

    def test_header_shows_this_weeks_numbers(self):
        post.publish(_rep(), "D1", cl=FakeSlack())          # Fri 9/18: 1 of 2 removed
        rep = _rep(); rep.day = dt.date(2026, 9, 21)
        for c in rep.candidates:
            c.qualify = "Qualify"                           # Mon 9/21: nobody removed
        cl = FakeSlack()
        post.publish(rep, "D1", cl=cl)
        self.assertIn("- 0% Removed", cl.updates[-1]["text"])
        self.assertIn("this week", cl.updates[-1]["text"])

    def test_new_ad_gets_its_own_thread(self):
        post.publish(_rep(), "D1", cl=FakeSlack())
        rep = _rep(); rep.day = dt.date(2026, 9, 22)
        rep.candidates[1].ad = "new ad"
        rep.book.ads.append("new ad")
        c = post.publish(rep, "D1", cl=FakeSlack())
        self.assertEqual(c["threads_new"], 1)
        self.assertEqual(c["to_unpin"], [])

    def test_no_saturday(self):
        self.assertNotIn(5, post.config.POST_WEEKDAYS)


class SeedForeverTests(unittest.TestCase):
    def test_newest_week_becomes_the_forever_threads(self):
        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(post, "STATE_PATH", Path(tmp) / "s.json"),                 mock.patch.object(post.config, "ONE_THREAD_PER_AD", True):
            post.STATE_PATH.write_text(
                '{"C1": {"weeks": {"2026-09-14": {"a": {"thread_ts": "1.0", "days": ["2026-09-14"]}},'
                ' "2026-09-21": {"a": {"thread_ts": "2.0", "days": ["2026-09-21"]}}}}}',
                encoding="utf-8")
            st = post._load_state()
            self.assertEqual(st["C1"]["weeks"][post.FOREVER]["a"]["thread_ts"], "2.0")
            self.assertEqual(st["C1"]["weeks"]["2026-09-14"]["a"]["thread_ts"], "1.0")
