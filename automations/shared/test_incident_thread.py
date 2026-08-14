"""Tests for the corrections-channel incident threads.

The behaviour these lock down is the whole point of the module (Eve 2026-08-14):
a repeat must REPLY in the first message's thread, never add a second top-level
post, and a fix must be announced IN that thread and close it.

    python -m unittest automations.shared.test_incident_thread -v
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.shared import incident_thread as inc


class FakeClient:
    """Records posts; serves them back as channel history the way Slack does."""

    def __init__(self):
        self.posts = []          # (thread_ts or None, text)
        self.updates = []        # (ts, text)
        self._n = 0

    def chat_postMessage(self, *, channel, text, thread_ts=None, **_kw):
        self._n += 1
        ts = f"{self._n}.0000"
        self.posts.append((thread_ts, text))
        return {"ok": True, "ts": ts, "channel": channel}

    def chat_update(self, *, channel, ts, text, **_kw):
        self.updates.append((ts, text))
        # Slack really does rewrite the message, and the marker lives in it — a
        # fake that skipped this would hide whether resolve() closes the scan.
        i = int(float(ts)) - 1
        if 0 <= i < len(self.posts):
            self.posts[i] = (self.posts[i][0], text)
        return {"ok": True}

    def refuse_updates(self):
        """Simulate posting from a DIFFERENT machine/identity: chat.update is
        refused (`cant_update_message`), only replies get through."""
        def _boom(**_kw):
            raise RuntimeError("cant_update_message")
        self.chat_update = _boom

    def conversations_history(self, *, channel, limit=200, cursor=None):
        # Newest first, parents only — same shape as the real API.
        msgs = []
        for i, (thread_ts, text) in enumerate(self.posts, start=1):
            if thread_ts:
                continue
            replies = sum(1 for t, _ in self.posts if t == f"{i}.0000")
            msgs.append({"ts": f"{i}.0000", "text": text, "reply_count": replies})
        return {"messages": list(reversed(msgs))}

    # helpers
    @property
    def top_level(self):
        return [t for th, t in self.posts if not th]

    @property
    def replies(self):
        return [t for th, t in self.posts if th]


class IncidentThreadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._real_state = inc.STATE_PATH
        inc.STATE_PATH = Path(self.tmp.name) / "incident_threads.json"
        self.addCleanup(lambda: setattr(inc, "STATE_PATH", self._real_state))
        inc._HISTORY_CACHE.clear()
        self.addCleanup(inc._HISTORY_CACHE.clear)
        self.c = FakeClient()

    def _open(self, day, *, title="🚨 *r* — broke", body=("*Error:* boom",),
              details=("detail",), followup=None):
        inc._HISTORY_CACHE.clear()
        return inc.open_or_followup(key="failure-r", title=title, body=list(body),
                                    details=list(details), followup=followup,
                                    channel="C1", day=day, client=self.c)

    def test_first_time_posts_parent_and_detail(self):
        res = self._open(dt.date(2026, 8, 14))
        self.assertTrue(res["new"])
        self.assertEqual(len(self.c.top_level), 1)
        self.assertIn("_incident · failure-r · open 2026-08-14_",
                      self.c.top_level[0])
        self.assertEqual(self.c.replies, ["detail"])

    def test_repeat_replies_in_thread_not_a_new_post(self):
        first = self._open(dt.date(2026, 8, 14))
        again = self._open(dt.date(2026, 8, 15))
        self.assertFalse(again["new"])
        self.assertEqual(again["ts"], first["ts"])
        self.assertEqual(len(self.c.top_level), 1, "a repeat must not add a post")
        self.assertIn("Happened again", self.c.replies[-1])
        # The parent post IS the first occurrence, so the first reply is the 2nd.
        self.assertIn("2nd time", self.c.replies[-1])
        self.assertIn("since Fri Aug 14", self.c.replies[-1])
        # …and the third day counts up rather than repeating itself.
        self._open(dt.date(2026, 8, 16))
        self.assertEqual(len(self.c.top_level), 1)
        self.assertIn("3rd time", self.c.replies[-1])

    def test_repeat_found_with_no_local_index(self):
        """Another machine opened it — the marker in the message is the state."""
        self._open(dt.date(2026, 8, 14))
        inc.STATE_PATH.unlink()
        inc._HISTORY_CACHE.clear()
        again = self._open(dt.date(2026, 8, 15))
        self.assertFalse(again["new"])
        self.assertEqual(len(self.c.top_level), 1)

    def test_resolve_posts_in_thread_and_closes(self):
        first = self._open(dt.date(2026, 8, 14))
        ok = inc.resolve(key="failure-r", lines=["✅ *r* — RESOLVED."],
                         channel="C1", day=dt.date(2026, 8, 15), client=self.c)
        self.assertTrue(ok)
        self.assertEqual(self.c.replies[-1], "✅ *r* — RESOLVED.")
        self.assertEqual(self.c.updates[-1][0], first["ts"])
        self.assertIn("resolved 2026-08-15", self.c.updates[-1][1])
        self.assertNotIn("failure-r", inc.open_keys())
        # A NEW failure after the fix opens a fresh post, not the closed thread.
        after = self._open(dt.date(2026, 8, 20))
        self.assertTrue(after["new"])

    def test_resolve_closes_even_when_the_parent_edit_is_refused(self):
        """Cross-machine: the reply lands, the edit doesn't, and the incident
        still has to count as closed — otherwise the next failure replies into a
        thread everyone has stopped reading."""
        self._open(dt.date(2026, 8, 14))
        self.c.refuse_updates()
        self.assertTrue(inc.resolve(key="failure-r", lines=["✅ done"],
                                    channel="C1", day=dt.date(2026, 8, 15),
                                    client=self.c))
        self.assertEqual(self.c.replies[-1], "✅ done")
        after = self._open(dt.date(2026, 8, 20))
        self.assertTrue(after["new"])
        self.assertEqual(len(self.c.top_level), 2)

    def test_resolve_with_nothing_open_is_a_no_op(self):
        self.assertFalse(inc.resolve(key="failure-nope", lines=["x"],
                                     channel="C1", client=self.c))
        self.assertEqual(self.c.posts, [])

    def test_thread_ages_out_into_a_fresh_post(self):
        self._open(dt.date(2026, 8, 1))
        res = self._open(dt.date(2026, 9, 1))
        self.assertTrue(res["new"], "a month-old thread should start over")
        self.assertEqual(len(self.c.top_level), 2)
        self.assertIn("Still not fixed after 31 day(s)", self.c.replies[-2])

    def test_unsafe_key_is_refused_not_posted_wrong(self):
        self.assertIsNone(inc.open_or_followup(key="has space", title="t",
                                               body=["b"], channel="C1",
                                               client=self.c))
        self.assertEqual(self.c.posts, [])

    def test_dry_run_touches_nothing(self):
        res = inc.open_or_followup(key="failure-r", title="t", body=["b"],
                                   channel="C1", dry_run=True, client=self.c)
        self.assertTrue(res["new"])
        self.assertEqual(self.c.posts, [])
        self.assertFalse(inc.STATE_PATH.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
