"""An exact group name breaks a "contains" tie; nothing else does.

2026-09-21: Megan made "Lucy Test" and Aya made "Indelible Lucy Test". The
lookup matches by contains, so "Lucy Test" matched both and every send to it
refused -- including the automatic test board queued for the next day.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.b2b_dispositions import text_post as tp

HITS = [{"id": "a", "name": "Indelible Lucy Test", "participants": "2"},
        {"id": "b", "name": "Lucy Test", "participants": "2"}]


class ExactNameTiebreakTest(unittest.TestCase):
    def _resolve(self, name, hits=HITS):
        with mock.patch.object(tp, "find_groups", return_value=hits):
            return tp.resolve_group(name)

    def test_the_exact_name_wins_a_contains_tie(self):
        self.assertEqual(self._resolve("Lucy Test")["id"], "b")

    def test_the_longer_name_still_resolves(self):
        self.assertEqual(self._resolve("Indelible Lucy Test")["id"], "a")

    def test_no_exact_match_still_refuses(self):
        with self.assertRaises(tp.GroupTextError):
            self._resolve("Test")

    def test_two_exact_matches_still_refuse(self):
        twins = [{"id": "x", "name": "Lucy Test", "participants": "2"},
                 {"id": "y", "name": "Lucy Test", "participants": "5"}]
        with self.assertRaises(tp.GroupTextError):
            self._resolve("Lucy Test", twins)

    def test_one_match_is_unchanged(self):
        self.assertEqual(self._resolve("Lucy Test", HITS[1:])["id"], "b")


class TextgroupActionTest(unittest.TestCase):
    def test_needs_the_separator(self):
        from automations.day_orchestrator import mini_control as M
        ok, msg = M._action_textgroup("Lucy Test hello")
        self.assertFalse(ok)

    def test_sends_through_the_production_sender(self):
        from automations.day_orchestrator import mini_control as M
        with mock.patch.object(tp, "send_text_to_group",
                               return_value={"resolved_name": "Lucy Test",
                                             "participants": "2",
                                             "chat_id": "b"}) as s:
            ok, msg = M._action_textgroup("Lucy Test :: hello")
        self.assertTrue(ok, msg)
        self.assertEqual(s.call_args.args[:2], ("Lucy Test", "hello"))
        self.assertIs(s.call_args.kwargs.get("dry_run"), False)


class TextgroupUnwrapsQueueQuotingTest(unittest.TestCase):
    def test_a_quoted_arg_from_the_queue_is_unwrapped(self):
        """The first live send looked for "'Lucy Test" -- the queue had
        shlex-quoted the whole argument because it contained spaces."""
        import shlex
        from automations.day_orchestrator import mini_control as M
        raw = shlex.join(["Lucy Test :: hello there"])
        with mock.patch.object(tp, "send_text_to_group",
                               return_value={"resolved_name": "Lucy Test",
                                             "participants": "2",
                                             "chat_id": "b"}) as s:
            ok, _msg = M._action_textgroup(raw)
        self.assertTrue(ok)
        self.assertEqual(s.call_args.args[:2], ("Lucy Test", "hello there"))


if __name__ == "__main__":
    unittest.main()
