"""Pass timing: logged every run, one heads-up a day past the limit.

    python -m unittest automations.online_presence.test_timing
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.online_presence import timing as T


class FakeSlack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)


class Timing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(T, "LOG", Path(self.tmp.name) / "t.jsonl"),
                  mock.patch.object(T, "WARNED", Path(self.tmp.name) / "w.json")]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()

    def test_logged_and_quiet_under_the_limit(self):
        cl = FakeSlack()
        T.record("pass", 95, offices=2, cl=cl)
        self.assertEqual(cl.posts, [])
        self.assertIn("1m 35s", T.summary())

    def test_slow_pass_warns_once_a_day_in_corrections(self):
        cl, day = FakeSlack(), dt.datetime(2026, 11, 10, 12)
        self.assertTrue(T.record("pass", 400, offices=12, cl=cl, now=day)["warned"])
        self.assertFalse(T.record("pass", 410, offices=12, cl=cl, now=day)["warned"])
        self.assertEqual(len(cl.posts), 1)
        self.assertEqual(cl.posts[0]["channel"], T.OPS_CHANNEL)
        self.assertIn("6m 40s", cl.posts[0]["text"])
        T.record("pass", 420, offices=12, cl=cl, now=day + dt.timedelta(days=1))
        self.assertEqual(len(cl.posts), 2)

    def test_friday_limit_is_an_hour(self):
        cl = FakeSlack()
        T.record("weekly", 3000, cl=cl)
        self.assertEqual(cl.posts, [])
        T.record("weekly", 3700, cl=cl)
        self.assertEqual(len(cl.posts), 1)

    def test_dry_runs_never_warn(self):
        cl = FakeSlack()
        T.record("pass", 999, cl=cl, live=False)
        self.assertEqual(cl.posts, [])

    def test_summary_with_nothing(self):
        self.assertIn("no runs logged yet", T.summary())


if __name__ == "__main__":
    unittest.main()
