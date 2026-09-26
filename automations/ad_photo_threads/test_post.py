"""python -m unittest automations.ad_photo_threads.test_post

A fake Slack client only — nothing here touches the real Slack (see
project_tests-sysmodules-mock-posted-to-real-slack: the client is passed in,
never patched through sys.modules)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.ad_photo_threads import collect, post, titles
from automations.ad_photo_threads.titles import TitleBook, norm


class FakeSlack:
    def __init__(self):
        self.posts, self.uploads, self.pins, self._n = [], [], [], 0
        self.gone = set()          # thread headers deleted by hand

    def conversations_replies(self, **kw):
        if kw["ts"] in self.gone:
            raise RuntimeError("The server responded with: {'ok': False, 'error': 'thread_not_found'}")
        return {"messages": [{"ts": kw["ts"], "user": "ULUCY"}]}

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
        cl.conversations_history = lambda **kw: {"messages": [
            {"ts": "200.1", "user": "ULUCY", "files": [{"id": "F8"}]},   # loose reply
            {"ts": "200.2", "user": "UEVE"},
            {"ts": "200.3", "user": "ULUCY", "subtype": "channel_join"}]}
        c = post.retire_channel("C1", cl=cl)
        self.assertEqual(gone, ["100.2", "100.1", "200.1"])  # replies, header, loose
        self.assertEqual(files, ["F9", "F8"])
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

    def test_backfilling_last_week_keeps_this_weeks_header(self):
        rep = _rep(); rep.day = dt.date(2026, 9, 21)
        for c in rep.candidates:
            c.qualify = "Qualify"                           # this week: 0% removed
        post.publish(rep, "D1", cl=FakeSlack())
        cl = FakeSlack()
        c = post.publish(_rep(), "D1", cl=cl)               # Fri 9/18, added after
        self.assertEqual(c["threads_new"], 0)
        self.assertIn("- 0% Removed", cl.updates[-1]["text"])

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


class RetireWeekTests(unittest.TestCase):
    def test_deletes_untouched_old_threads_only(self):
        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(post, "STATE_PATH", Path(tmp) / "s.json"),                 mock.patch.object(post.config, "ONE_THREAD_PER_AD", True):
            post._save_state({"C1": {"weeks": {
                "2026-09-14": {"a": {"thread_ts": "1.0"}, "b": {"thread_ts": "2.0"},
                               "c": {"thread_ts": "9.0"}},
                "forever": {"c": {"thread_ts": "9.0"}}}}})
            cl = FakeSlack()
            cl.auth_test = lambda: {"user_id": "ULUCY"}
            cl.conversations_replies = lambda **kw: {"messages": [
                {"ts": kw["ts"], "user": "ULUCY"}]
                + ([{"ts": "2.5", "user": "URAF"}] if kw["ts"] == "2.0" else [])}
            gone = []
            cl.chat_delete = lambda **kw: gone.append(kw["ts"])
            cl.files_delete = lambda **kw: None
            c = post.retire_week("C1", dt.date(2026, 9, 14), cl=cl)
            self.assertEqual(gone, ["1.0"])
            self.assertEqual((c["kept_touched"], c["kept_forever"]), (1, 1))
            wk = post._load_state()["C1"]["weeks"]["2026-09-14"]
            self.assertEqual(sorted(wk), ["b", "c"])


class DeletedThreadTests(PublishTests):
    test_one_thread_one_reply_group_photo_once = None

    def test_reply_to_a_deleted_thread_opens_a_new_one_not_a_loose_post(self):
        post.publish(_rep(), "C1", cl=FakeSlack())          # thread 100.1
        rep = _rep(); rep.day = dt.date(2026, 9, 17)        # same week, new day
        cl = FakeSlack(); cl._n = 4; cl.gone = {"100.1"}
        c = post.publish(rep, "C1", cl=cl)
        self.assertEqual(c["threads_new"], 1)
        self.assertEqual(cl.uploads[0]["thread_ts"], "100.5")

    def test_retire_survives_a_thread_already_deleted(self):
        post.publish(_rep(), "C1", cl=FakeSlack())
        cl = FakeSlack(); cl.gone = {"100.1"}
        cl.auth_test = lambda: {"user_id": "ULUCY"}
        cl.conversations_history = lambda **kw: {"messages": []}
        post.retire_channel("C1", cl=cl)
        self.assertNotIn("C1", post._load_state())


class MergeOldCompanyKeyTests(PublishTests):
    test_one_thread_one_reply_group_photo_once = None

    def test_old_key_with_company_tail_moves_its_people_not_deletes_them(self):
        # 9/23 Carlos: the duplicate's key was saved with the company tail;
        # the merge must still find its candidate and move them.
        base = "Event Marketing & Sales Assistant (Spanish Needed), 2 locations"
        tail = "Event Marketing & Sales Assistant (Spanish Needed) – 2 locations – Vantura Acquisition"
        img = {"id": "F1", "mimetype": "image/png"}
        rep = collect.DayReport(day=dt.date(2026, 9, 22), book=TitleBook([base] * 5))
        rep.candidates = [
            collect.Candidate("Ana Uno", base, "A", "Qualify", "", "x", ad=norm(base), images=[img]),
            collect.Candidate("Bo Dos", tail, "A", "Qualify", "", "x", ad=norm(base), images=[img])]
        post.publish(rep, "C1", cl=FakeSlack())
        st = post._load_state()
        wk = st["C1"]["weeks"][post.bucket(rep.day)]
        old_key = titles.norm_keep_company(tail)
        wk[old_key] = {"thread_ts": "55.0", "days": ["2026-09-22"], "title": "dup"}
        post._save_state(st)
        cl = FakeSlack()
        cl.auth_test = lambda: {"user_id": "ULUCY"}
        gone = []
        cl.chat_delete = lambda **kw: gone.append(kw["ts"])
        cl.files_delete = lambda **kw: None
        got = post.merge_dups("C1", rep.day, build=lambda d: rep, cl=cl)
        self.assertIn("moved 1", list(got.values())[0])
        self.assertIn("Bo Dos", cl.uploads[0]["initial_comment"])

    def test_key_with_tail_finds_a_row_typed_without_it(self):
        # 9/25 Khalil: thread saved as "... 3 locations everforward", the
        # sheet row now reads "..., 3 locations" (no tail) -- still theirs.
        base = "AT&T Retail Associate (Spanish Required), 3 locations"
        row = "AT&T Retail Associate (Bilingual Spanish Required), 3 locations"
        img = {"id": "F1", "mimetype": "image/png"}
        book = TitleBook([base] * 5, aliases={row: base})
        rep = collect.DayReport(day=dt.date(2026, 9, 16), book=book)
        rep.candidates = [
            collect.Candidate("Ana Uno", base, "A", "Qualify", "", "x", ad=norm(base), images=[img]),
            collect.Candidate("Diana Dos", row, "A", "Qualify", "", "x", ad=norm(base), images=[img])]
        post.publish(rep, "C1", cl=FakeSlack())
        st = post._load_state()
        wk = st["C1"]["weeks"][post.bucket(rep.day)]
        for k in [k for k in wk if k != norm(base)]:
            del wk[k]
        wk[norm(row) + " everforward"] = {"thread_ts": "57.0", "days": ["2026-09-16"], "title": "dup"}
        post._save_state(st)
        cl = FakeSlack(); cl.auth_test = lambda: {"user_id": "ULUCY"}
        cl.chat_delete = lambda **kw: None
        cl.files_delete = lambda **kw: None
        got = post.merge_dups("C1", rep.day, build=lambda d: rep, cl=cl)
        self.assertIn("moved 1", got["dup"])
        self.assertIn("Diana Dos", cl.uploads[0]["initial_comment"])
        self.assertNotIn("Ana Uno", cl.uploads[0]["initial_comment"])

    def test_merge_never_deletes_a_thread_whose_people_it_cant_find(self):
        base = "Retail Associate, Euless, TX"
        rep = collect.DayReport(day=dt.date(2026, 9, 22), book=TitleBook([base] * 5))
        rep.candidates = [collect.Candidate("Ana Uno", base, "A", "Qualify", "", "x", ad=norm(base))]
        post.publish(rep, "C1", cl=FakeSlack())
        st = post._load_state()
        wk = st["C1"]["weeks"][post.bucket(rep.day)]
        wk["retail associate euless tx vantura acquisition"] = {"thread_ts": "56.0", "days": ["2026-09-22"]}
        post._save_state(st)
        cl = FakeSlack(); cl.auth_test = lambda: {"user_id": "ULUCY"}
        gone = []
        cl.chat_delete = lambda **kw: gone.append(kw["ts"])
        got = post.merge_dups("C1", rep.day, build=lambda d: rep, cl=cl)
        self.assertEqual(gone, [])
        self.assertIn("left alone", list(got.values())[0])


class UnmergeTests(PublishTests):
    test_one_thread_one_reply_group_photo_once = None

    def _setup(self, fixed: bool):
        g = "Retail Associate – Garland TX"
        i = "Retail Associate – Irving TX"
        img = {"id": "F1", "mimetype": "image/png"}
        book = TitleBook([g] * 5 + [i] * 3) if fixed else TitleBook([g] * 5)
        rep = collect.DayReport(day=dt.date(2026, 9, 16), book=book)
        rep.candidates = [
            collect.Candidate("Ana Uno", g, "A", "Qualify", "", "x", ad=norm(g), images=[img]),
            collect.Candidate("Iris Dos", i, "A", "Qualify", "", "x",
                              ad=book.resolve(i), images=[img])]
        st = post._load_state()
        wk = st.setdefault("C1", {}).setdefault("weeks", {}).setdefault(post.bucket(rep.day), {})
        wk[norm(g)] = {"thread_ts": "10.0", "days": ["2026-09-16"], "title": g,
                       "merged": {norm(i): ["2026-09-16"]}}
        post._save_state(st)
        cl = FakeSlack(); cl.auth_test = lambda: {"user_id": "ULUCY"}
        cl.conversations_replies = lambda **kw: {"messages": [
            {"ts": "10.0", "user": "ULUCY"}, {"ts": "11.0", "user": "ULUCY"},
            {"ts": "12.0", "user": "ULUCY", "files": [{"id": "F9"}]}]}
        cl.gone = []
        cl.chat_delete = lambda **kw: cl.gone.append(kw["ts"])
        cl.files_delete = lambda **kw: None
        return rep, cl, i, g

    def test_moves_the_people_back_into_their_own_thread(self):
        rep, cl, i, g = self._setup(fixed=True)
        got = post.unmerge("C1", i, ["12.0"], build=lambda d: rep, cl=cl)
        self.assertEqual(cl.gone, ["12.0"])
        self.assertEqual(got["reposted_days"], ["2026-09-16"])
        self.assertIn("Iris Dos", cl.uploads[-1]["initial_comment"])
        self.assertNotIn("Ana Uno", cl.uploads[-1]["initial_comment"])
        wk = post._load_state()["C1"]["weeks"][post.bucket(rep.day)]
        self.assertIn(norm(i), wk)
        self.assertNotIn(norm(i), wk[norm(g)].get("merged", {}))

    def test_deletes_nothing_while_the_ad_still_folds(self):
        rep, cl, i, g = self._setup(fixed=False)
        got = post.unmerge("C1", i, ["12.0"], build=lambda d: rep, cl=cl)
        self.assertIn("error", got)
        self.assertEqual(cl.gone, [])


class PinBackfillTests(unittest.TestCase):
    """The one-time pass that pins threads opened before Lucy had pins:write."""

    STATE = {
        "C0AAA": {"weeks": {
            "2026-09-14": {"old": {"thread_ts": "1.0", "title": "Last week"}},
            "forever": {
                "b": {"thread_ts": "3.0", "title": "Beta"},
                "a": {"thread_ts": "2.0", "title": "Alpha", "pinned": True},
                "c": {"thread_ts": "", "title": "No thread yet"},
            }}},
        "D0DM1": {"weeks": {"forever": {"x": {"thread_ts": "9.0", "title": "DM"}}}},
        "_scheduled_merges_done": {"2026-09-21": True},
    }

    def _run(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(post, "STATE_PATH", Path(tmp.name) / "s.json"), \
                mock.patch.object(post.config, "ONE_THREAD_PER_AD", True), \
                mock.patch.object(post.time, "sleep", lambda *_: None):
            post.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            post._save_state(json.loads(json.dumps(self.STATE)))
            cl = kw.pop("cl", FakeSlack())
            got = post.pin_backfill(cl=cl, logfn=lambda *_: None, **kw)
            return got, cl, post._load_state()

    def test_dry_run_lists_without_pinning_or_saving(self):
        got, cl, state = self._run(dry_run=True)
        self.assertEqual(got["C0AAA"]["pinned"], ["Beta"])
        self.assertEqual(got["C0AAA"]["already"], ["Alpha"])
        self.assertEqual(got["C0AAA"]["no_thread"], ["No thread yet"])
        self.assertEqual(cl.pins, [])                       # Slack untouched
        self.assertFalse(state["C0AAA"]["weeks"]["forever"]["b"].get("pinned"))

    def test_apply_pins_the_live_bucket_only_and_records_it(self):
        got, cl, state = self._run(dry_run=False, pace=0)
        self.assertEqual(cl.pins, [("add", "3.0")])         # not "1.0": history
        self.assertEqual(got["C0AAA"]["pinned"], ["Beta"])
        self.assertTrue(state["C0AAA"]["weeks"]["forever"]["b"]["pinned"])

    def test_dms_and_bookkeeping_keys_are_skipped(self):
        got, cl, _ = self._run(dry_run=False, pace=0)
        self.assertEqual(sorted(got), ["C0AAA"])
        self.assertNotIn(("add", "9.0"), cl.pins)

    def test_a_refused_pin_is_reported_not_recorded(self):
        cl = FakeSlack()
        cl.pins_add = lambda **kw: (_ for _ in ()).throw(
            RuntimeError("{'ok': False, 'error': 'not_in_channel'}"))
        got, _, state = self._run(dry_run=False, pace=0, cl=cl)
        self.assertIn("Beta", got["C0AAA"]["failed"])
        self.assertFalse(state["C0AAA"]["weeks"]["forever"]["b"].get("pinned"))

    def test_rate_limit_backs_off_then_succeeds(self):
        cl, calls = FakeSlack(), []

        def flaky(**kw):
            calls.append(kw)
            if len(calls) == 1:
                raise RuntimeError("{'ok': False, 'error': 'ratelimited'}")
            cl.pins.append(("add", kw["timestamp"]))
        cl.pins_add = flaky
        got, _, state = self._run(dry_run=False, pace=0, cl=cl)
        self.assertEqual(len(calls), 2)                     # retried, not failed
        self.assertEqual(got["C0AAA"]["failed"], {})
        self.assertTrue(state["C0AAA"]["weeks"]["forever"]["b"]["pinned"])
