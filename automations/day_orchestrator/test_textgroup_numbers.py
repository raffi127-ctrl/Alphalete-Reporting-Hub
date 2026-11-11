"""`textgroup` can address a group text by the people in it (2026-11-10).

Oren's intro text was refused by name: 15 chats on Lucy 1 match "A Players".
Made-up 555 numbers.
"""
import unittest
from unittest import mock

from automations.day_orchestrator import mini_control as M

A, B, C = "+13135550142", "+13135550199", "+19015550107"


class TextgroupNumbersTest(unittest.TestCase):
    def test_numbers_become_a_pinned_destination(self):
        dest = M._textgroup_numbers("313-555-0142, (313) 555-0199,+19015550107")
        self.assertEqual(dest["require_handles"], [A, B, C])

    def test_a_name_stays_a_name(self):
        for name in ("A Players", "Team 5", "Box Team 🔥", "3135550142",
                     "313-555-0142, A Players", "313-555-0142, 12345"):
            self.assertIsNone(M._textgroup_numbers(name), name)

    def test_the_action_sends_by_people_when_given_numbers(self):
        sent = {}

        def fake(group, text, dry_run=True, dest=None):
            sent.update(group=group, text=text, dry_run=dry_run, dest=dest)
            return {"resolved_name": "A Players", "participants": "10", "chat_id": "x"}

        with mock.patch("automations.b2b_dispositions.text_post.send_text_to_group", fake):
            ok, said = M._action_textgroup("'%s,%s,%s :: Hi team, it'\"'\"'s Lucy'" % (A, B, C))
        self.assertTrue(ok, said)
        self.assertEqual(sent["dest"]["require_handles"], [A, B, C])
        self.assertEqual(sent["text"], "Hi team, it's Lucy")
        self.assertFalse(sent["dry_run"])

    def test_the_action_still_sends_by_name(self):
        sent = {}

        def fake(group, text, dry_run=True, dest=None):
            sent.update(group=group, dest=dest)
            return {"resolved_name": group, "participants": "4", "chat_id": "x"}

        with mock.patch("automations.b2b_dispositions.text_post.send_text_to_group", fake):
            ok, _ = M._action_textgroup("Lucy Test :: hello")
        self.assertTrue(ok)
        self.assertEqual((sent["group"], sent["dest"]), ("Lucy Test", None))


if __name__ == "__main__":
    unittest.main()
