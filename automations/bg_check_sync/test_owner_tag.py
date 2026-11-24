"""The daily 5 PM owner tag in the BG Status thread (owner_tag.py)."""
from __future__ import annotations

import datetime as dt
import unittest

from automations.bg_check_sync import owner_tag as OT

RAF_CH = next(iter(OT.OWNERS))
RAF_ID = OT.OWNERS[RAF_CH]["slack_id"]
# 2026-11-24 17:05 Central = 23:05 UTC.
AT_5PM = dt.datetime(2026, 11, 24, 23, 5, tzinfo=dt.timezone.utc)
AT_4PM = dt.datetime(2026, 11, 24, 22, 5, tzinfo=dt.timezone.utc)


class FakeClient:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "1.1"}


class TimingTests(unittest.TestCase):

    def test_not_before_5pm_local(self):
        self.assertFalse(OT.due({}, "America/Chicago", AT_4PM))

    def test_at_5pm_local(self):
        self.assertTrue(OT.due({}, "America/Chicago", AT_5PM))

    def test_once_a_day(self):
        self.assertFalse(OT.due({"tagged_on": "2026-11-24"}, "America/Chicago",
                                AT_5PM))

    def test_local_means_the_offices_zone(self):
        """23:05 UTC is 3:05 PM in LA — not their 5 PM yet."""
        self.assertFalse(OT.due({}, "America/Los_Angeles", AT_5PM))


class RenderTests(unittest.TestCase):

    def test_first_tag_gives_totals_and_mentions_owner(self):
        txt = OT.render(RAF_ID, "11/30/2026", None,
                        {"Ana Diaz": "Passed", "Bo Li": "awaiting"})
        self.assertIn(f"<@{RAF_ID}>", txt)
        self.assertIn("2 scheduled", txt)

    def test_changes_are_listed(self):
        prev = {"Ana Diaz": "awaiting", "Bo Li": "Taken - Pending", "Cy Ro": "Sent"}
        cur = {"Ana Diaz": "Passed", "Bo Li": "Failed", "Di Wu": "awaiting"}
        txt = OT.render(RAF_ID, "11/30/2026", prev, cur)
        self.assertIn("✅ Passed: Ana Diaz", txt)
        self.assertIn("❌ Failed: Bo Li", txt)
        self.assertIn("Added to the week: Di Wu", txt)
        self.assertIn("No longer on the week: Cy Ro", txt)

    def test_no_change_still_says_so(self):
        cur = {"Ana Diaz": "Passed"}
        txt = OT.render(RAF_ID, "11/30/2026", dict(cur), cur)
        self.assertIn("No background check changes", txt)

    def test_sent_and_blank_are_the_same_bucket(self):
        """Sent → blank is not a change worth a line; both are 'not taken yet'."""
        self.assertEqual(OT.snapshot([("A", "Sent"), ("B", "")]),
                         {"A": "awaiting", "B": "awaiting"})


class MaybeTagTests(unittest.TestCase):

    def test_posts_in_the_thread_and_remembers(self):
        chans = {RAF_CH: {"parent_ts": "9.9", "reply_ts": "9.10"}}
        c = FakeClient()
        done = OT.maybe_tag("11/30/2026", [("Ana Diaz", "Passed")], chans,
                            client=c, dry_run=False, now_utc=AT_5PM, log=lambda *_: None)
        self.assertEqual(done, [RAF_CH])
        self.assertEqual(c.posts[0]["thread_ts"], "9.9")
        self.assertEqual(chans[RAF_CH]["tagged_on"], "2026-11-24")
        self.assertEqual(chans[RAF_CH]["tag_snapshot"], {"Ana Diaz": "Passed"})
        # Same day, next hourly pass: nothing.
        OT.maybe_tag("11/30/2026", [("Ana Diaz", "Passed")], chans,
                     client=c, dry_run=False, now_utc=AT_5PM, log=lambda *_: None)
        self.assertEqual(len(c.posts), 1)

    def test_channel_without_owner_is_never_tagged(self):
        chans = {"C_NOBODY": {"parent_ts": "9.9"}}
        c = FakeClient()
        OT.maybe_tag("11/30/2026", [("A", "Passed")], chans, client=c,
                     dry_run=False, now_utc=AT_5PM, log=lambda *_: None)
        self.assertEqual(c.posts, [])

    def test_dry_run_posts_nothing(self):
        chans = {RAF_CH: {"parent_ts": "9.9"}}
        c = FakeClient()
        OT.maybe_tag("11/30/2026", [("A", "Passed")], chans, client=c,
                     dry_run=True, now_utc=AT_5PM, log=lambda *_: None)
        self.assertEqual(c.posts, [])
        self.assertNotIn("tagged_on", chans[RAF_CH])

    def test_slack_error_never_raises(self):
        class Boom:
            def chat_postMessage(self, **kw):
                raise RuntimeError("channel_not_found")
        chans = {RAF_CH: {"parent_ts": "9.9"}}
        OT.maybe_tag("11/30/2026", [("A", "Passed")], chans, client=Boom(),
                     dry_run=False, now_utc=AT_5PM, log=lambda *_: None)
        self.assertNotIn("tagged_on", chans[RAF_CH])


if __name__ == "__main__":
    unittest.main()
