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
                contact_email="hr@kash.example", gbp_location="")
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
        p = _office(post_hours=(0, 23))
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
    def test_name_from_the_ids_doc(self):
        from automations.online_presence import setup
        self.assertEqual(setup.resolve_person("Kash Rai", cl=object()), "U046XBPN0G2")

    def test_an_id_passes_straight_through(self):
        from automations.online_presence import setup
        self.assertEqual(setup.resolve_person("U046XBPN0G2", cl=object()), "U046XBPN0G2")


if __name__ == "__main__":
    unittest.main()
