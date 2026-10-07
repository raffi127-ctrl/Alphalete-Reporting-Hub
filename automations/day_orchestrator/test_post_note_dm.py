"""`post_note users=U1,U2 <text>` sends a private group DM, not a channel post.

Eve 2026-10-06: a note for one owner (Eveliz's SaraPlus code) "tiene que ir a
un DM privado con megan y evelyn" -- and post_note only took channels.
"""
import unittest

from automations.day_orchestrator import test_post_note_thread as T
from automations.day_orchestrator.mini_control import _action_post_note


class _Slack(T._Slack):
    def __init__(self):
        super().__init__()
        self.opened = []

    def conversations_open(self, **kw):
        self.opened.append(kw)
        return {"channel": {"id": "C0GROUPDM1"}}


class GroupDM(unittest.TestCase):

    def _run(self, args):
        from unittest import mock
        s = _Slack()
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=s):
            ok, msg = _action_post_note(args)
        return ok, msg, s

    def test_users_open_one_dm_and_post_into_it(self):
        ok, msg, s = self._run("users=U048WU3EUFJ,U04G5HJBGFN,U088E2KJEV8 Hi\nthere")
        self.assertTrue(ok, msg)
        self.assertEqual(s.opened, [{"users": "U048WU3EUFJ,U04G5HJBGFN,U088E2KJEV8"}])
        self.assertEqual(s.calls[0]["channel"], "C0GROUPDM1")
        self.assertEqual(s.calls[0]["text"], "Hi\nthere")

    def test_a_bad_id_posts_nothing(self):
        ok, _msg, s = self._run("users=eveliz Hi")
        self.assertFalse(ok)
        self.assertEqual(s.calls, [])
        self.assertEqual(s.opened, [])


if __name__ == "__main__":
    unittest.main()
