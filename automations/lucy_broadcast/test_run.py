"""Offline tests for Lucy Broadcast — fake Slack client + fake senders, so
nothing here can post or text.

    python -m unittest automations.lucy_broadcast.test_run
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.lucy_broadcast import config, run

NOW = 1_800_000_000.0


class FakeClient:
    def __init__(self, messages):
        self.messages = messages
        self.reactions = []
        self.replies = []

    def auth_test(self):
        return {"user_id": "ULUCY"}

    def conversations_history(self, channel, limit):
        return {"messages": self.messages}

    def conversations_info(self, channel):
        return {"channel": {"name": "dest-" + channel}}

    def users_info(self, user):
        return {"user": {"profile": {"display_name": "Raf"}}}

    def reactions_add(self, channel, timestamp, name):
        self.reactions.append((timestamp, name))

    def chat_postMessage(self, **kw):
        self.replies.append(kw)
        return {"ok": True}


def post(ts_offset, text="Team meeting at 9", **kw):
    m = {"ts": "%.6f" % (NOW - ts_offset), "user": "URAF", "text": text}
    m.update(kw)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(run, "_STATE", self.tmp / "state.json"),
            mock.patch.object(config, "SLACK_DESTINATIONS", ("C1", "C2")),
            mock.patch.object(config, "IMESSAGE_GROUPS", ("Leaders",)),
            mock.patch.object(config, "APPROVED_POSTERS", ()),
            mock.patch("automations.day_orchestrator.hub_publish.publish_done",
                       lambda *a, **k: None),
        ]
        for p in self.patches:
            p.start()
        self.slack_sent, self.texts = [], []

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def slack(self, cl, ch, text, files):
        self.slack_sent.append((ch, text))

    def imsg(self, group, text, files):
        self.texts.append((group, text))

    def go(self, cl, **kw):
        kw.setdefault("slack_sender", self.slack)
        kw.setdefault("imessage_sender", self.imsg)
        return run.scan(dry_run=False, channel="CSRC", cl=cl, now=NOW, **kw)

    def baseline(self):
        run._save_state({"_baselined": True})


class TestFilter(unittest.TestCase):
    def ok(self, m):
        return run.is_broadcast_post(m, own_user="ULUCY", now=NOW, settle=60)

    def test_plain_post_counts(self):
        self.assertTrue(self.ok(post(120)))

    def test_too_fresh_waits(self):
        self.assertFalse(self.ok(post(10)))

    def test_lucys_own_reply_skipped(self):
        self.assertFalse(self.ok(post(120, user="ULUCY")))

    def test_bot_and_join_skipped(self):
        self.assertFalse(self.ok(post(120, bot_id="B1")))
        self.assertFalse(self.ok(post(120, subtype="channel_join")))

    def test_blank_never_relayed(self):
        self.assertFalse(self.ok(post(120, text="  ")))

    def test_picture_only_counts(self):
        self.assertTrue(self.ok(post(120, text="", files=[{"name": "a.png"}])))


class TestPlain(unittest.TestCase):
    def test_markup(self):
        s = run.slack_to_plain(
            "<!channel> *Big* news from <@U1>: see <https://x.com|the flyer> "
            "&amp; join <#C9|sales>", {"U1": "Raf"})
        self.assertEqual(s, "Big news from @Raf: see the flyer (https://x.com) "
                            "& join #sales")

    def test_keeps_snake_case_and_math(self):
        self.assertEqual(run.slack_to_plain("file_name_here 2*3*4"),
                         "file_name_here 2*3*4")


class TestScan(Base):
    def test_first_run_baselines_and_sends_nothing(self):
        cl = FakeClient([post(120)])
        acts = self.go(cl)
        self.assertEqual([a["action"] for a in acts], ["baselined"])
        self.assertEqual(self.slack_sent + self.texts, [])
        self.assertEqual(self.go(cl), [])           # and stays quiet after

    def test_sends_everywhere_once(self):
        self.baseline()
        cl = FakeClient([post(120, text="Hi <@U1>")])
        self.go(cl)
        self.assertEqual(self.slack_sent, [("C1", "Hi <@U1>"), ("C2", "Hi <@U1>")])
        self.assertEqual(self.texts, [("Leaders", "Hi @Raf")])
        self.assertIn(("%.6f" % (NOW - 120), "white_check_mark"), cl.reactions)
        self.go(cl)                                 # next tick: no repeats
        self.assertEqual(len(self.slack_sent), 2)
        self.assertEqual(len(self.texts), 1)

    def test_failed_leg_retries_alone(self):
        self.baseline()
        cl = FakeClient([post(120)])
        calls = {"n": 0}

        def flaky(group, text, files):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Messages timed out")
            self.texts.append(group)

        self.go(cl, imessage_sender=flaky)
        self.assertEqual(len(self.slack_sent), 2)
        self.assertEqual(self.texts, [])
        self.assertEqual(cl.reactions, [])          # not done yet, no ✅
        self.go(cl, imessage_sender=flaky)
        self.assertEqual(len(self.slack_sent), 2)   # Slack NOT re-sent
        self.assertEqual(self.texts, ["Leaders"])
        self.assertEqual(cl.reactions[-1][1], "white_check_mark")

    def test_gives_up_and_says_so(self):
        self.baseline()
        cl = FakeClient([post(120)])

        def dead(group, text, files):
            raise RuntimeError("no such group")

        for _ in range(config.MAX_ATTEMPTS):
            self.go(cl, imessage_sender=dead)
        self.assertEqual(cl.reactions[-1][1], "warning")
        self.assertIn("Leaders", cl.replies[-1]["text"])
        n = len(cl.replies)
        self.go(cl, imessage_sender=dead)           # gave up = stays quiet
        self.assertEqual(len(cl.replies), n)

    def test_unapproved_poster_ignored(self):
        self.baseline()
        with mock.patch.object(config, "APPROVED_POSTERS", ("USOMEONE",)):
            acts = self.go(FakeClient([post(120)]))
        self.assertEqual(acts[0]["action"], "ignored_unapproved")
        self.assertEqual(self.slack_sent, [])

    def test_refuses_loop_and_empty_config(self):
        with mock.patch.object(config, "SLACK_DESTINATIONS", ("CSRC",)):
            with self.assertRaises(run.BroadcastError):
                self.go(FakeClient([]))
        with mock.patch.object(config, "SLACK_DESTINATIONS", ()), \
                mock.patch.object(config, "IMESSAGE_GROUPS", ()):
            with self.assertRaises(run.BroadcastError):
                self.go(FakeClient([]))
        with self.assertRaises(run.BroadcastError):
            run.scan(dry_run=True, channel="", cl=FakeClient([]))

    def test_dry_run_sends_and_saves_nothing(self):
        cl = FakeClient([post(120)])
        with mock.patch.object(run, "_preview_imessage", lambda g: "found"):
            acts = run.scan(dry_run=True, channel="CSRC", cl=cl, now=NOW,
                            slack_sender=self.slack, imessage_sender=self.imsg)
        self.assertTrue(acts[0]["dry_run"])
        self.assertEqual(self.slack_sent + self.texts, [])
        self.assertFalse(run._STATE.exists())


if __name__ == "__main__":
    unittest.main()
