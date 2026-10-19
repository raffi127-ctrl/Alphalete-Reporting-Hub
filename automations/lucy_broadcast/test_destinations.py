"""Offline tests for the thread-driven destination list.

    python -m unittest automations.lucy_broadcast.test_destinations
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.lucy_broadcast import config, destinations as dz, run
from automations.lucy_broadcast.test_run import NOW, FakeClient, post

CHANS = {"C7": "alphalete-gp-sales", "C1": "alphalete-sales", "C2": "a-players-b2b", "CSRC": "lucy-broadcast"}
GROUPS = ["A Players", "A Players Leaders", "Admin Staff", "Alphalete Owners🔥"]
THREAD = "1700000000.000100"


def reply(ts, text, user="URAF", **kw):
    m = {"ts": ts, "user": user, "text": text, "thread_ts": THREAD}
    m.update(kw)
    return m


class TestParse(unittest.TestCase):
    def p(self, text):
        return dz.parse_reply(text, CHANS, GROUPS)

    def test_channel_link(self):
        self.assertEqual(self.p("send to <#C1|alphalete-sales>")["slack"], ["C1"])

    def test_typed_hash_name(self):
        self.assertEqual(self.p("pls add #a-players-b2b")["slack"], ["C2"])

    def test_channel_lucy_isnt_in(self):
        r = self.p("add <#C9|secret> and #nope")
        self.assertEqual(r["slack"], [])
        self.assertEqual(r["not_member"], ["#secret", "#nope"])

    def test_group_longest_wins(self):
        self.assertEqual(self.p("add the A Players Leaders text")["groups"],
                         ["A Players Leaders"])
        self.assertEqual(self.p("a players and admin staff please")["groups"],
                         ["A Players", "Admin Staff"])

    def test_casual_words_dont_match(self):
        r = self.p("thanks! sales are looking great")
        self.assertEqual((r["slack"], r["groups"]), ([], []))

    def test_bare_channel_name_one_per_reply(self):
        self.assertEqual(self.p("alphalete-sales")["slack"], ["C1"])
        self.assertEqual(self.p("Please add the alphalete sales channel")["slack"], ["C1"])
        r = self.p("remove alphalete-sales")
        self.assertEqual((r["remove"], r["slack"]), (True, ["C1"]))
        self.assertEqual(self.p("sales")["slack"], [])        # partial name: no

    def test_megans_instruction_reply_adds_nothing(self):
        r = self.p("REPLY here with one channel / imessage per reply so we can "
                   "remove them- Lucy will read this thread EACH time so that "
                   "any deleted or added channels are updated!")
        self.assertEqual((r["slack"], r["groups"], r["not_member"]), ([], [], []))

    def test_megans_label_format(self):
        self.assertEqual(self.p("Slack Channel: alphalete-gp-sales")["slack"], ["C7"])
        self.assertEqual(self.p("Imessage Group - Alphalete Owners:fire: - Real")["groups"],
                         ["Alphalete Owners🔥"])
        self.assertEqual(self.p("Imessage Group - Alphalete Owners:fire:")["groups"],
                         ["Alphalete Owners🔥"])

    def test_emoji_in_group_name_matches_slack_code(self):
        r = dz.parse_reply("Owners Real:fire:", {}, ["Owners Real🔥"])
        self.assertEqual(r["groups"], ["Owners Real🔥"])

    def test_examples_reply_adds_nothing(self):
        r = self.p("*EXAMPLES:* \n\nImessage Group - Alphalete Owners:fire: - Real"
                   "\n\nSlack Channel: alphalete-gp-sales")
        self.assertEqual((r["slack"], r["groups"]), ([], []))

    def test_removal(self):
        r = self.p("please remove #alphalete-sales")
        self.assertTrue(r["remove"])
        self.assertEqual(r["slack"], ["C1"])
        self.assertTrue(self.p("don't send to Admin Staff anymore")["remove"])


class TestReplay(unittest.TestCase):
    def test_add_then_remove_in_order(self):
        slack, texts, _ = dz.replay([
            reply("2", "add #alphalete-sales and A Players"),
            reply("3", "also <#C2|a-players-b2b>"),
            reply("4", "stop sending to #alphalete-sales"),
        ], CHANS, GROUPS)
        self.assertEqual(slack, ["C2"])
        self.assertEqual(texts, ["A Players"])

    def test_deleted_reply_stops_counting(self):
        slack, _, _ = dz.replay([], CHANS, GROUPS)
        self.assertEqual(slack, [])


class ThreadClient(FakeClient):
    def __init__(self, messages, replies):
        super().__init__(messages)
        self.thread = replies

    def conversations_replies(self, channel, ts, limit, cursor=None):
        return {"messages": [{"ts": THREAD, "user": "UMEGAN", "text": "how it works"}]
                + self.thread}

    def users_conversations(self, **kw):
        return {"channels": [{"id": k, "name": v} for k, v in CHANS.items()]}

    def conversations_info(self, channel):
        return {"channel": {"name": CHANS.get(channel, channel)}}


class TestScanWithThread(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(run, "_STATE", self.tmp / "state.json"),
            mock.patch.object(config, "SLACK_DESTINATIONS", ()),
            mock.patch.object(config, "IMESSAGE_GROUPS", ()),
            mock.patch.object(config, "APPROVED_POSTERS", ()),
            mock.patch.object(config, "DESTINATIONS_THREAD_TS", THREAD),
            mock.patch("automations.day_orchestrator.hub_publish.publish_done",
                       lambda *a, **k: None),
        ]
        for p in self.patches:
            p.start()
        run._save_state({"_baselined": True})
        self.sent = []

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def go(self, cl, groups=GROUPS, dry=False):
        return run.scan(
            dry_run=dry, channel="CSRC", cl=cl, now=NOW,
            slack_sender=lambda cl, c, t, f: self.sent.append(("slack", c)),
            imessage_sender=lambda g, t, f: self.sent.append(("text", g)),
            groups_reader=lambda: groups)

    def test_sends_to_what_the_thread_says(self):
        cl = ThreadClient([post(120)], [
            reply("1700000001.0", "add #alphalete-sales + A Players"),
            reply("1700000002.0", "ok", user="ULUCY"),   # Lucy's own -> ignored
        ])
        self.go(cl)
        self.assertEqual(self.sent, [("slack", "C1"), ("text", "A Players")])
        summary = [r for r in cl.replies if r.get("thread_ts") == THREAD]
        self.assertEqual(len(summary), 1)
        self.assertIn("#alphalete-sales", summary[0]["text"])
        self.assertIn(("1700000001.0", "white_check_mark"), cl.reactions)

    def test_summary_posted_once_per_reply(self):
        cl = ThreadClient([], [reply("1700000001.0", "add #alphalete-sales")])
        self.go(cl)
        self.go(cl)
        self.assertEqual(len([r for r in cl.replies
                              if r.get("thread_ts") == THREAD]), 1)

    def test_edited_reply_is_answered_again(self):
        r1 = reply("1700000001.0", "add #alphalete-sales")
        cl = ThreadClient([], [r1])
        self.go(cl)
        r1["text"] = "add #a-players-b2b"
        r1["edited"] = {"ts": "1700000099.0"}
        self.go(cl)
        self.assertEqual(len([r for r in cl.replies
                              if r.get("thread_ts") == THREAD]), 2)

    def test_source_channel_never_a_destination(self):
        cl = ThreadClient([post(120)], [reply("1700000001.0",
                                              "add #lucy-broadcast #alphalete-sales")])
        self.go(cl)
        self.assertEqual(self.sent, [("slack", "C1")])

    def test_cant_read_groups_sends_nothing(self):
        cl = ThreadClient([post(120)], [reply("1700000001.0", "add #alphalete-sales")])
        with self.assertRaises(run.BroadcastError):
            self.go(cl, groups=None)
        self.assertEqual(self.sent, [])

    def test_first_run_doesnt_answer_old_chatter(self):
        cl = ThreadClient([], [reply("1700000001.0", "reply here, one per reply")])
        self.go(cl)
        self.assertEqual((cl.replies, cl.reactions), ([], []))
        cl.thread.append(reply("1700000005.0", "hello?"))
        self.go(cl)                                 # a NEW unclear reply is answered
        self.assertIn("Couldn't tell", cl.replies[-1]["text"])

    def test_dry_run_posts_no_summary(self):
        cl = ThreadClient([post(120)], [reply("1700000001.0", "add #alphalete-sales")])
        self.go(cl, groups=None, dry=True)
        self.assertEqual(cl.replies, [])
        self.assertEqual(cl.reactions, [])


if __name__ == "__main__":
    unittest.main()
