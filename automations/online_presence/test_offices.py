"""Online presence per office: Alphalete unchanged, offices kept apart, dry by default.

    python -m unittest automations.online_presence.test_offices

Nothing here touches Slack, Google or Zoho: the Slack client is a fake that
records calls, and every file lives in a temp folder.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from automations.online_presence import offices


def _office(**kw):
    base = dict(key="kash", business_name="Kash Marketing",
                slack_channel="C0KASHROOM", approvers=("U046XBPN0G2",),
                contact_email="hr@kash.example", gbp_location="",
                owner_slack_id="U046XBPN0G2", pages=("instagram", "facebook"),
                address="100 Main St, Dallas, TX 75201", phone="214-555-0100",
                website="https://kash.example", google_link="https://maps.google.com/maps?cid=1",
                instagram_url="https://instagram.com/kash", facebook_url="https://facebook.com/kash")
    base.update(kw)
    return offices.Presence(**base)


class FakeSlack:
    def __init__(self, messages=None):
        self.calls = []
        self.messages = messages or []

    def conversations_history(self, **kw):
        self.calls.append(("history", kw))
        return {"messages": self.messages}

    def conversations_replies(self, **kw):
        self.calls.append(("replies", kw))
        return {"messages": []}

    def chat_postMessage(self, **kw):
        self.calls.append(("post", kw))
        return {"ts": "9.9"}

    def reactions_add(self, **kw):
        self.calls.append(("react", kw))


class AlphaleteIsUnchanged(unittest.TestCase):
    """The shared code now takes a profile; Alphalete's must be what it was."""

    def test_same_rooms_people_and_settings(self):
        from automations.brand_audit import config as C
        a = offices.alphalete()
        self.assertEqual(a.slack_channel, C.SOCIAL_INBOX_CHANNEL_ID)
        self.assertEqual(a.reviews_channel, C.ALERT_SLACK_CHANNEL_ID)
        self.assertEqual(a.counted_approvers, tuple(C.SOCIAL_APPROVERS))
        self.assertEqual(a.contact_email, C.REVIEW_REPLY_CONTACT)
        self.assertEqual(a.gbp_location, C.GBP_LOCATION_PATH)
        self.assertEqual(a.auto_reply_min_stars, C.AUTO_POST_MIN_STARS)
        self.assertEqual(a.auto_reply_daily_cap, C.AUTO_POST_DAILY_CAP)

    def test_same_files(self):
        from automations.brand_audit import (review_replies, social_inbox,
                                             style, zoho_draft)
        a = offices.alphalete()
        self.assertEqual(a.path("review_replies.json"), review_replies._STATE)
        self.assertEqual(a.path("social_inbox.json"), social_inbox._STATE)
        self.assertEqual(a.style_file, style._FILE)
        self.assertEqual(a.zoho_profile, zoho_draft.ZOHO_PROFILE_DIR)

    def test_reply_voice_still_signs_alphalete(self):
        from automations.brand_audit import review_replies as R
        neg = R._negative_system("Alphalete Marketing")
        self.assertIn("hr@alphaletemarketing.com", neg)
        self.assertIn("Alphalete Marketing", R._positive_system("Alphalete Marketing"))


class OfficeVoice(unittest.TestCase):
    def test_office_name_and_email_replace_alphalete(self):
        from automations.brand_audit import review_replies as R
        pos = R._positive_system("Kash Marketing")
        neg = R._negative_system("Kash Marketing", "hr@kash.example")
        for text in (pos, neg):
            self.assertIn("Kash Marketing", text)
            self.assertNotIn("Alphalete Marketing", text)
        self.assertIn("hr@kash.example", neg)
        self.assertNotIn("hr@alphaletemarketing.com", neg)


class Rows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "offices.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_and_load_round_trip_keeps_other_rows(self):
        offices.save(_office(), self.file)
        offices.save(_office(key="cyrus", business_name="Cyrus Co"), self.file)
        offices.save(_office(contact_email="new@kash.example"), self.file)
        rows = offices.load(self.file)
        self.assertEqual(sorted(rows), ["cyrus", "kash"])
        self.assertEqual(rows["kash"].contact_email, "new@kash.example")
        self.assertEqual(rows["cyrus"].business_name, "Cyrus Co")
        self.assertIsInstance(rows["kash"].approvers, tuple)

    def test_new_office_starts_dry(self):
        self.assertEqual(_office().mode, "dry")
        self.assertFalse(_office().is_live)

    def test_typo_in_a_field_is_refused(self):
        self.file.write_text(json.dumps([{"key": "kash", "business_name": "K",
                                          "slack_channel": "C1", "aproovers": []}]))
        with self.assertRaises(ValueError):
            offices.load(self.file)

    def test_an_office_cannot_point_at_alphaletes_files(self):
        self.file.write_text(json.dumps([{"key": "kash", "business_name": "K",
                                          "slack_channel": "C1",
                                          "state_dir": "/Users/x/.config/brand-audit"}]))
        with self.assertRaises(ValueError):
            offices.load(self.file)

    def test_alphalete_is_not_a_row(self):
        with self.assertRaises(ValueError):
            offices.save(_office(key="alphalete"), self.file)


class KeptApart(unittest.TestCase):
    def test_each_office_has_its_own_folder_and_zoho(self):
        a, b = _office(), _office(key="cyrus")
        self.assertNotEqual(a.folder, b.folder)
        self.assertNotEqual(a.zoho_profile, b.zoho_profile)
        self.assertNotEqual(a.style_file, offices.alphalete().style_file)
        self.assertNotEqual(a.path("review_replies.json"),
                            offices.alphalete().path("review_replies.json"))

    def test_nobody_named_means_megan_and_eve_not_anyone(self):
        p = _office(approvers=())
        self.assertEqual(p.counted_approvers, offices.FALLBACK_APPROVERS)

    def test_a_reps_check_does_not_approve(self):
        from automations.brand_audit.social_inbox import _reacted
        p = _office()
        rep_only = [{"name": "white_check_mark", "users": ["UREP0001"]}]
        owner = [{"name": "white_check_mark", "users": ["U046XBPN0G2"]}]
        self.assertFalse(_reacted(rep_only, ("white_check_mark",), p.counted_approvers))
        self.assertTrue(_reacted(owner, ("white_check_mark",), p.counted_approvers))

    def test_one_room_holds_photos_and_reviews(self):
        p = _office()
        self.assertEqual(p.reviews_channel, p.slack_channel)


class Problems(unittest.TestCase):
    def test_missing_pieces_are_named(self):
        p = _office(business_name="", contact_email="", post_hours=(7, 20))
        probs = " ".join(p.problems())
        self.assertIn("business name", probs)
        self.assertIn("contact email", probs)
        self.assertIn("8am and 6pm", probs)

    def test_complete_office_has_none(self):
        self.assertEqual(_office().problems(), [])


class ReviewsPerOffice(unittest.TestCase):
    def test_no_listing_yet_does_nothing_and_touches_no_slack(self):
        from automations.brand_audit import review_replies as R
        with mock.patch.object(R, "_client", side_effect=AssertionError("slack")):
            acts = R.process_reviews(dry_run=True, profile=_office())
        self.assertEqual(acts[0]["action"], "no_listing")

    def test_office_never_falls_back_to_alphaletes_places_sample(self):
        from automations.brand_audit import review_replies as R
        with mock.patch.object(R.google_reviews, "collect",
                               side_effect=AssertionError("places")):
            self.assertEqual(R.get_reviews(None, ""), [])


class PhotosPerOffice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def test_reads_the_offices_room_not_alphaletes(self):
        from automations.brand_audit import social_inbox as S
        fake = FakeSlack()
        with mock.patch.object(S, "_client", return_value=fake):
            S.process_inbox(dry_run=True, profile=_office())
        chans = {kw.get("channel") for _, kw in fake.calls}
        self.assertEqual(chans, {"C0KASHROOM"})

    def _hour_now(self, p):
        return dt.datetime.now(ZoneInfo(p.timezone)).hour

    def test_free_zoho_posts_inside_the_window_dry(self):
        from automations.brand_audit import social_inbox as S
        p = _office(post_hours=(0, 23), post_via="lucy")
        fake = FakeSlack()
        acts = S._office_publish(p, fake, "1.1", {"photo_path": "x.jpg"},
                                 "cap", True, p.path("zoho_schedule.json"),
                                 p.zoho_profile)
        self.assertEqual(acts[0]["action"], "post_now")
        self.assertEqual(fake.calls, [])             # dry: nothing said

    def test_outside_the_window_it_waits(self):
        from automations.brand_audit import social_inbox as S
        p = _office()
        p = _office(post_hours=((self._hour_now(p) + 12) % 24,))
        acts = S._office_publish(p, FakeSlack(), "1.1", {}, "cap", True,
                                 p.path("zoho_schedule.json"), p.zoho_profile)
        self.assertEqual(acts[0]["action"], "waiting_for_window")

    def test_one_post_a_day_on_the_offices_clock(self):
        from automations.brand_audit import social_inbox as S
        p = _office(post_hours=(0, 23))
        f = p.path("zoho_schedule.json")
        f.parent.mkdir(parents=True, exist_ok=True)
        today = dt.datetime.now(ZoneInfo(p.timezone)).date().isoformat()
        f.write_text(json.dumps({"last_scheduled_date": today}))
        acts = S._office_publish(p, FakeSlack(), "1.1", {}, "cap", True, f,
                                 p.zoho_profile)
        self.assertEqual(acts[0]["action"], "waiting_for_tomorrow")

    def test_already_out_is_never_sent_twice(self):
        from automations.brand_audit import social_inbox as S
        p = _office(post_hours=(0, 23))
        for st in ({"published": True}, {"scheduled": True}):
            self.assertEqual(S._office_publish(p, FakeSlack(), "1.1", st, "c",
                                               False, p.path("z.json"),
                                               p.zoho_profile), [])


class OfficeComputerPosts(unittest.TestCase):
    """post_via 'eco': the ICD's own computer posts from the ICD's own Zoho."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def test_every_office_posts_from_its_own_computer_by_default(self):
        self.assertEqual(_office().post_via, "eco")
        self.assertEqual(offices.alphalete().post_via, "lucy")

    def test_approved_post_is_queued_not_posted_and_dry_queues_nothing(self):
        from automations.brand_audit import social_inbox as S
        p = _office(post_hours=(0, 23))
        with mock.patch("automations.online_presence.relay.enqueue_post",
                        side_effect=AssertionError("queued on a dry pass")):
            acts = S._office_publish(p, FakeSlack(), "1.1", {"photo_path": "x.jpg"},
                                     "cap", True, p.path("zoho_schedule.json"), None)
        self.assertEqual(acts[0]["action"], "queue_to_office")
        self.assertEqual(acts[0]["pages"], ["instagram", "facebook"])

    def test_live_queues_once_and_takes_todays_slot(self):
        from automations.brand_audit import social_inbox as S
        p = _office(post_hours=(0, 23))
        photo = Path(self.tmp.name) / "p.jpg"
        photo.write_bytes(b"jpg")
        st = {"photo_path": str(photo)}
        sched = p.path("zoho_schedule.json")
        with mock.patch("automations.online_presence.relay.enqueue_post",
                        return_value="JOB1") as q:
            S._office_publish(p, FakeSlack(), "1.1", st, "cap", False, sched, None)
            again = S._office_publish(p, FakeSlack(), "1.1", st, "cap", False, sched, None)
        self.assertEqual(q.call_count, 1)
        self.assertEqual(st["eco_job"], "JOB1")
        self.assertEqual(again, [])
        st2 = {"photo_path": str(photo)}
        with mock.patch("automations.online_presence.relay.enqueue_post",
                        side_effect=AssertionError("second post today")):
            acts = S._office_publish(p, FakeSlack(), "2.2", st2, "c", False, sched, None)
        self.assertEqual(acts[0]["action"], "waiting_for_tomorrow")


class ChosenPagesOnly(unittest.TestCase):
    """DM the owner only when a page THEY chose drops out of their Zoho."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def _check(self, channels, status="ok", dry=False, p=None):
        from automations.online_presence import watch
        fake = FakeSlack()
        acts = watch.collect(p or _office(), [{"job_id": "J", "kind": "social_check",
                                               "answered": True,
                                               "result": {"status": status,
                                                          "channels": channels}}],
                             fake, dry=dry)
        dms = [kw for k, kw in fake.calls if k == "post"]
        return acts, dms

    def test_all_chosen_connected_no_dm(self):
        acts, dms = self._check(["instagram", "facebook"])
        self.assertEqual(dms, [])
        self.assertEqual(acts[0]["action"], "check_ok")

    def test_an_unchosen_page_missing_is_not_news(self):
        acts, dms = self._check(["instagram", "facebook"])     # no X, no Google
        self.assertEqual(dms, [])

    def test_a_chosen_page_missing_dms_the_owner_once_a_day(self):
        acts, dms = self._check(["instagram"])
        self.assertEqual(len(dms), 1)
        self.assertEqual(dms[0]["channel"], "U046XBPN0G2")
        self.assertIn("Facebook", dms[0]["text"])
        self.assertNotIn("Instagram", dms[0]["text"])
        _, again = self._check(["instagram"])
        self.assertEqual(again, [])

    def test_signed_out_says_so(self):
        _, dms = self._check([], status="signed_out")
        self.assertIn("signed out", dms[0]["text"])

    def test_personal_linkedin_is_not_the_company_page(self):
        from automations.online_presence import watch
        self.assertEqual(watch.connected_pages(["linkedinprofile"]), set())

    def test_dry_pass_sends_nothing(self):
        _, dms = self._check(["instagram"], dry=True)
        self.assertEqual(dms, [])


class PostAnswers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = mock.patch.object(offices, "STATE_ROOT", Path(self.tmp.name))
        self.root.start()
        from automations.brand_audit import social_inbox as S
        self.S, self.p = S, _office()
        S._save_state({"1.1": {"eco_job": "J1", "caption": "c"}},
                      self.p.path("social_inbox.json"))

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def _answer(self, result):
        from automations.online_presence import watch
        fake = FakeSlack()
        acts = watch.collect(self.p, [{"job_id": "J1", "kind": "social_post",
                                       "answered": True, "result": result}],
                             fake, dry=False)
        return acts, fake, self.S._load_state(self.p.path("social_inbox.json"))["1.1"]

    def test_posted_gets_the_rocket(self):
        acts, fake, st = self._answer({"status": "posted",
                                       "channels": ["instagram", "facebook"]})
        self.assertTrue(st["posted"])
        self.assertIn(("react", {"channel": "C0KASHROOM", "name": "rocket",
                                 "timestamp": "1.1"}), fake.calls)

    def test_blocked_tells_the_room_dms_owner_and_retries_later(self):
        acts, fake, st = self._answer({"status": "signed_out", "channels": []})
        self.assertNotIn("eco_job", st)              # will be queued again
        chans = [kw["channel"] for k, kw in fake.calls if k == "post"]
        self.assertEqual(sorted(chans), ["C0KASHROOM", "U046XBPN0G2"])

    def test_error_mid_post_is_never_retried(self):
        acts, fake, st = self._answer({"status": "error", "error": "boom"})
        self.assertEqual(st["eco_job"], "J1")
        self.assertEqual(st["post_error"], "boom")
        self.assertEqual([k for k, _ in fake.calls if k == "post"], [])


class DryTwiceOver(unittest.TestCase):
    def _run(self, *, live_flag, mode):
        from automations.online_presence import run
        seen = {}

        def rv(**kw):
            seen["reviews"] = kw["dry_run"]
            return []

        def ib(**kw):
            seen["photos"] = kw["dry_run"]
            return []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(offices, "STATE_ROOT", Path(d)), \
                mock.patch("automations.online_presence.watch.ensure_daily_check",
                           lambda p, live: None), \
                mock.patch("automations.brand_audit.review_replies.process_reviews", rv), \
                mock.patch("automations.brand_audit.social_inbox.process_inbox", ib):
            run.run_office(_office(mode=mode), live=live_flag)
        return seen

    def test_only_both_together_post(self):
        self.assertEqual(self._run(live_flag=False, mode="live"),
                         {"reviews": True, "photos": True})
        self.assertEqual(self._run(live_flag=True, mode="dry"),
                         {"reviews": True, "photos": True})
        self.assertEqual(self._run(live_flag=True, mode="live"),
                         {"reviews": False, "photos": False})


class SlackNames(unittest.TestCase):
    def test_page_words(self):
        from automations.online_presence import setup
        self.assertEqual([setup._page(w) for w in ("IG", "Facebook", "twitter", "Google")],
                         ["instagram", "facebook", "x", "google"])
        with self.assertRaises(ValueError):
            setup._page("myspace")

    def test_name_from_the_ids_doc(self):
        from automations.online_presence import setup
        self.assertEqual(setup.resolve_person("Kash Rai", cl=object()), "U046XBPN0G2")

    def test_an_id_passes_straight_through(self):
        from automations.online_presence import setup
        self.assertEqual(setup.resolve_person("U046XBPN0G2", cl=object()), "U046XBPN0G2")


if __name__ == "__main__":
    unittest.main()
