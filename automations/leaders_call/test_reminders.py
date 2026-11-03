"""Leader's Call countdown: the clock picks the right message, a late fire stays
quiet, and a repeat fire can't double-post. No network: the Slack client is fake."""
from __future__ import annotations

import datetime as dt
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.leaders_call import reminders as r
from automations.leaders_call import run

MON = dt.date(2026, 11, 9)


def at(hour, minute, day=MON):
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=r.CENTRAL)


class FakeClient:
    def __init__(self, fail_on=()):
        self.posts, self.fail_on = [], set(fail_on)

    def chat_postMessage(self, channel, text, **_):
        if channel in self.fail_on:
            raise RuntimeError("not_in_channel")
        self.posts.append((channel, text))
        return {"ok": True}


class SlotFor(unittest.TestCase):
    def test_each_time_picks_its_message(self):
        self.assertEqual(r.slot_for(at(20, 45)), 15)
        self.assertEqual(r.slot_for(at(20, 55)), 5)
        self.assertEqual(r.slot_for(at(21, 0)), 0)

    def test_a_late_fire_posts_nothing(self):
        for h, m in ((20, 44), (20, 50), (20, 59), (21, 11), (23, 0)):
            with self.subTest(time=f"{h}:{m}"):
                self.assertIsNone(r.slot_for(at(h, m)))

    def test_only_mondays(self):
        self.assertIsNone(r.slot_for(at(20, 45, dt.date(2026, 11, 10))))

    def test_the_plist_fires_inside_every_slot_on_monday(self):
        path = Path(r.__file__).resolve().parents[2] / "deploy" / \
            "com.alphalete.leaders-call-reminders.plist"
        entries = plistlib.loads(path.read_bytes())["StartCalendarInterval"]
        self.assertEqual({e["Weekday"] for e in entries}, {1})
        fired = {r.slot_for(at(e["Hour"], e["Minute"])) for e in entries}
        self.assertEqual(fired, {15, 5, 0})


class Messages(unittest.TestCase):
    def test_every_message_has_the_link_and_the_call_is_at_nine(self):
        self.assertEqual(run.CALL_TIME, "9:00")
        for slot in (15, 5, 0):
            self.assertIn(run.ZOOM_URL, r.message_for(slot))

    def test_a_reminder_can_not_be_mistaken_for_the_deck_post(self):
        for slot in (15, 5, 0):
            self.assertNotIn("Weekly Recognition", r.message_for(slot))


class Send(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(r, "STATE_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cids = [cid for _, cid in r.FINAL_CHANNELS]

    def test_posts_to_both_deck_channels(self):
        c = FakeClient()
        self.assertEqual(r.send(15, dry_run=False, day=MON, client=c), 0)
        self.assertEqual([p[0] for p in c.posts], self.cids)

    def test_a_second_fire_does_not_double_post(self):
        c = FakeClient()
        r.send(15, dry_run=False, day=MON, client=c)
        r.send(15, dry_run=False, day=MON, client=c)
        self.assertEqual(len(c.posts), len(self.cids))

    def test_the_next_slot_still_posts(self):
        c = FakeClient()
        r.send(15, dry_run=False, day=MON, client=c)
        r.send(5, dry_run=False, day=MON, client=c)
        self.assertEqual(len(c.posts), 2 * len(self.cids))

    def test_one_failed_channel_does_not_stop_the_other_and_retry_fills_it(self):
        bad = FakeClient(fail_on=[self.cids[0]])
        self.assertEqual(r.send(5, dry_run=False, day=MON, client=bad), 1)
        self.assertEqual([p[0] for p in bad.posts], [self.cids[1]])
        good = FakeClient()
        self.assertEqual(r.send(5, dry_run=False, day=MON, client=good), 0)
        self.assertEqual([p[0] for p in good.posts], [self.cids[0]])

    def test_dry_run_posts_nothing_and_remembers_nothing(self):
        c = FakeClient()
        self.assertEqual(r.send(0, dry_run=True, day=MON, client=c), 0)
        self.assertEqual(c.posts, [])
        self.assertEqual(list(r.STATE_DIR.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
