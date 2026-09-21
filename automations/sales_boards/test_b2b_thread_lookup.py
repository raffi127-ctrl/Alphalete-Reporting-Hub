"""Looking up the day's B2B Metrics thread must never post.

2026-09-21 08:08: a laptop checking whether a board had landed called the old
`metrics_thread_ts`, which CREATED the parent whenever this machine's
thread_state.json had no entry (it only lives on the Lucy that posted) — two
empty "*B2B Metrics 09/21/2026*" posts went up on top of Lucy's real threads.

Offline: a fake Slack client, the state file patched. Nothing is sent.

    python -m unittest automations.sales_boards.test_b2b_thread_lookup
"""
import datetime as dt
import unittest
from unittest import mock

import automations.b2b_quality.run as bq
from automations.sales_boards import run as sb

DAY = dt.date(2026, 9, 21)
HEADER = "*B2B Metrics 09/21/2026*"


class FakeSlack:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.posted = []

    def conversations_history(self, **kw):
        return {"messages": self.messages}

    def chat_postMessage(self, **kw):
        self.posted.append(kw)
        return {"ts": "9999.0001"}


class LookupNeverPosts(unittest.TestCase):

    def setUp(self):
        self.state = {}
        self.saved = []
        p1 = mock.patch.object(bq, "_load_state",
                               lambda day, chan: dict(self.state))
        p2 = mock.patch.object(bq, "_save_state",
                               lambda *a, **k: self.saved.append(a))
        p3 = mock.patch.object(sb, "_b2b_header", lambda today: HEADER)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_no_state_no_thread_returns_none_and_posts_nothing(self):
        # The 08:08 case: laptop, no local state, and (here) no thread.
        slack = FakeSlack()
        self.assertIsNone(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY))
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.saved, [])

    def test_no_state_finds_lucys_thread_in_slack(self):
        # The laptop has no state file, but Lucy's 05:11 thread is there.
        slack = FakeSlack([{"ts": "1789985472.675019", "text": HEADER}])
        self.assertEqual(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY),
                         "1789985472.675019")
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.saved, [])

    def test_the_oldest_parent_wins_over_a_stray_duplicate(self):
        # History comes newest-first; the real thread is the earliest one.
        slack = FakeSlack([{"ts": "1789996106.872179", "text": HEADER},
                           {"ts": "1789985472.675019", "text": HEADER}])
        self.assertEqual(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY),
                         "1789985472.675019")

    def test_a_reply_quoting_the_title_is_not_a_parent(self):
        slack = FakeSlack([{"ts": "5.0", "thread_ts": "4.0", "text": HEADER}])
        self.assertIsNone(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY))

    def test_state_file_answers_without_asking_slack(self):
        self.state = {"thread_ts": "1.1"}
        slack = FakeSlack()
        slack.conversations_history = mock.Mock(side_effect=AssertionError)
        self.assertEqual(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY), "1.1")

    def test_old_creating_name_is_gone(self):
        # Anything still calling it should fail loudly, not post.
        self.assertFalse(hasattr(sb, "metrics_thread_ts"))


class OpenerPostsOnlyWhenNothingExists(unittest.TestCase):

    def setUp(self):
        self.saved = []
        p1 = mock.patch.object(bq, "_load_state", lambda day, chan: {})
        p2 = mock.patch.object(bq, "_save_state",
                               lambda *a, **k: self.saved.append(a))
        p3 = mock.patch.object(sb, "_b2b_header", lambda today: HEADER)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_missing_state_but_thread_in_slack_reuses_it(self):
        slack = FakeSlack([{"ts": "1789985472.675019", "text": HEADER}])
        ts = sb.open_b2b_metrics_thread(slack, "C1", DAY)
        self.assertEqual(ts, "1789985472.675019")
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.saved[0][2], "1789985472.675019")

    def test_nothing_anywhere_opens_one(self):
        slack = FakeSlack()
        ts = sb.open_b2b_metrics_thread(slack, "C1", DAY)
        self.assertEqual(ts, "9999.0001")
        self.assertEqual(len(slack.posted), 1)
        self.assertEqual(slack.posted[0]["text"], HEADER)


if __name__ == "__main__":
    unittest.main()
