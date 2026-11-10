"""Reddit / Indeed / Glassdoor mentions from Lucy's inbox -> the office.

    python -m unittest automations.online_presence.test_email_alerts

The inbox and Slack are fakes; nothing is read from Gmail or sent.
"""
from __future__ import annotations

import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from automations.online_presence.rooms import SOCIAL_ALERTS as ALERT_SLACK_CHANNEL_ID
from automations.online_presence import email_alerts as E, offices


def _mail(frm, subject, body):
    m = EmailMessage()
    m["From"], m["Subject"] = frm, subject
    m.set_content(body)
    return m.as_bytes()


class FakeInbox:
    def __init__(self, msgs):
        self.msgs = dict(msgs)            # uid -> bytes

    def uid(self, cmd, *args):
        if cmd == "search":
            return "OK", [" ".join(str(u) for u in sorted(self.msgs)).encode()]
        uid = int(args[0])
        return "OK", [(b"", self.msgs[uid])]


class FakeSlack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "3.%d" % len(self.posts)}


KASH = offices.Presence(key="kash", business_name="Palace Acquisitions", slack_channel="C0PALACE01",
                        owner_slack_id="U046XBPN0G2", mode="live")
F5 = _mail("F5Bot <admin@f5bot.com>", "F5Bot found something!",
           "Reddit Posts: /r/Devilcorp: Is Palace Acquisitions legit? "
           "https://www.reddit.com/r/Devilcorp/comments/abc/is_palace_acquisitions_legit/")
FWD_INDEED = _mail("Kash Rai <kash@palace.example>", "Fwd: You have a new review",
                   "---------- Forwarded message --------- From: Indeed <alert@indeed.com> "
                   "A new review was posted for Palace Acquisitions: 'pay was late' "
                   "https://www.indeed.com/cmp/Palace-Acquisitions/reviews")
REPORT = _mail("Robert Archey <rarchey@thesmartcircle.com>", "Residential Rep Counts",
               "Palace Acquisitions applicants this week via https://www.indeed.com/jobs?q=sales")


class Mentions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = mock.patch.object(E, "STATE", Path(self.tmp.name) / "s.json")
        self.state.start()

    def tearDown(self):
        self.state.stop()
        self.tmp.cleanup()

    def _run(self, msgs, live=True):
        cl = FakeSlack()
        return E.check([KASH], cl, live=live, mailbox=FakeInbox(msgs)), cl

    def test_first_look_seeds_quietly(self):
        acts, cl = self._run({1: F5})
        self.assertEqual(acts[0]["action"], "seeded")
        self.assertEqual(cl.posts, [])

    def test_reddit_alert_room_alerts_channel_owner(self):
        self._run({1: REPORT})
        acts, cl = self._run({1: REPORT, 2: F5})
        self.assertEqual([a["note"] for a in acts], ["Reddit · Palace Acquisitions"])
        chans = [p["channel"] for p in cl.posts]
        self.assertEqual(chans.count("C0PALACE01"), 2)
        self.assertEqual(chans.count(ALERT_SLACK_CHANNEL_ID), 2)
        self.assertIn("U046XBPN0G2", chans)
        self.assertIn("reddit.com/r/Devilcorp", cl.posts[1]["text"])

    def test_forwarded_indeed_review_alerts_and_says_notify_only(self):
        self._run({1: REPORT})
        acts, cl = self._run({1: REPORT, 2: FWD_INDEED})
        self.assertEqual(acts[0]["note"], "Indeed · Palace Acquisitions")
        self.assertIn("never replies on Indeed", cl.posts[1]["text"])

    def test_a_report_email_with_an_indeed_link_is_not_a_review(self):
        self._run({1: F5})
        acts, cl = self._run({1: F5, 2: REPORT})
        self.assertEqual((acts, cl.posts), ([], []))

    def test_each_message_once(self):
        self._run({1: REPORT})
        self._run({1: REPORT, 2: F5})
        acts, cl = self._run({1: REPORT, 2: F5})
        self.assertEqual(cl.posts, [])

    def test_other_offices_names_dont_match(self):
        other = _mail("admin@f5bot.com", "F5Bot found something!",
                      "Somebody Else Marketing https://reddit.com/r/x/comments/1/")
        self._run({1: REPORT})
        acts, cl = self._run({1: REPORT, 2: other})
        self.assertEqual(cl.posts, [])

    def test_dry_sends_nothing_and_keeps_the_place(self):
        self._run({1: REPORT})
        acts, cl = self._run({1: REPORT, 2: F5}, live=False)
        self.assertEqual(acts[0]["action"], "would_alert")
        self.assertEqual(cl.posts, [])
        acts, cl = self._run({1: REPORT, 2: F5})                  # still new for live
        self.assertEqual(acts[0]["action"], "mention_alert")


if __name__ == "__main__":
    unittest.main()
