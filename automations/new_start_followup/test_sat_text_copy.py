"""The Saturday text: Raf's 2026-09-05 wording, the thread link, and the
second message.

Three asks from his Slack message + Loom that day, all pinned here:

1. Reword the ask — "new starts that you have scheduled this Monday", plus a
   promise that the message to forward is attached.
2. Send that message as a SECOND iMessage. iMessage copies a whole message or
   nothing, so a script appended to the ask cannot be copied on its own —
   which is the entire reason it is a separate send.
3. Link to THAT WEEK'S THREAD, not the channel. The bare permalink dropped
   leaders in #rafs-office-recruiting-11280 to hunt for the post.

Run: python -m unittest automations.new_start_followup.test_sat_text_copy
"""
import unittest

from automations.new_start_followup import texts


class _Leader:
    def __init__(self, name, slack_id="U0TEST0001", phone="+12145551212"):
        self.name = name
        self.slack_id = slack_id
        self.phone = phone


class _Status:
    def __init__(self, name, owed=1):
        self.leader = _Leader(name)
        self.owed = owed


class _Rec:
    def __init__(self, thread):
        self.thread = thread


class AskWordingTests(unittest.TestCase):
    def test_matches_rafs_wording(self):
        text = texts.compose(_Status("Willvim Marte", owed=2), "2026-09-07")
        self.assertIn("Hey Willvim, it's Lucy!", text)
        self.assertIn("your new starts that you have scheduled this Monday", text)
        self.assertIn("reply Sent in the Slack thread once done please?", text)
        self.assertIn("I'll attach the message to send to them, just copy, "
                      "paste and edit your name and their name in the message "
                      "please!", text)

    def test_old_wording_is_gone(self):
        text = texts.compose(_Status("Willvim Marte", owed=2), "2026-09-07")
        self.assertNotIn("new starts that start this Monday", text)

    def test_singular_leader_still_reads_naturally(self):
        text = texts.compose(_Status("Rhea McKee", owed=1), "2026-09-07")
        self.assertIn("your new start that you have scheduled this Monday", text)

    def test_new_start_lines_still_ride_along(self):
        """The OBCL Phone column's ONLY legitimate use — handed to the leader,
        never a send target."""
        text = texts.compose(
            _Status("Willvim Marte", owed=2), "2026-09-07",
            starts=[("Franyerd Marti", "(321) 405-8046"),
                    ("Moises Turrubiartes", "(945) 365-7376")])
        self.assertIn("Franyerd Marti - (321) 405-8046", text)
        self.assertIn("Moises Turrubiartes - (945) 365-7376", text)


class ScriptMessageTests(unittest.TestCase):
    def test_script_is_its_own_message_not_part_of_the_ask(self):
        ask = texts.compose(_Status("Willvim Marte", owed=2), "2026-09-07")
        script = texts.compose_script()
        self.assertNotIn("Dress is business Professional", ask)
        self.assertNotIn("I look forward to seeing you", ask)
        self.assertIn("Dress is business Professional", script)

    def test_script_is_rafs_text_verbatim(self):
        script = texts.compose_script()
        self.assertTrue(script.startswith(
            "Hey X, this is X I look forward to seeing you at the office on "
            "Monday!"))
        self.assertIn("I know they told me that they got your gift all ready!",
                      script)
        self.assertIn("Out of everyone I've interviewed, I'm genuinely fired "
                      "up that you're one of the people starting on Monday.",
                      script)
        self.assertIn("Are you good with the office address? Is there anything "
                      "that you need from me?", script)
        self.assertTrue(script.rstrip().endswith("Shouldn't go longer than 5:00pm"))

    def test_script_keeps_the_X_placeholders(self):
        """Raf wants the leader to edit both names, and ONE template has to
        serve a leader with several new starts."""
        self.assertIn("Hey X, this is X", texts.compose_script())


class ThreadLinkTests(unittest.TestCase):
    def test_opens_the_thread_not_the_channel(self):
        link = texts.thread_link(_Rec({"channel": "C0AUAS88FGW",
                                       "anchor_ts": "1787501632.308139"}))
        self.assertIn("/archives/C0AUAS88FGW/p1787501632308139", link)
        # the tail is the whole point of the fix
        self.assertIn("thread_ts=1787501632.308139", link)
        self.assertIn("cid=C0AUAS88FGW", link)

    def test_channel_is_never_hardcoded(self):
        """The thread already moved once (2026-08-22); a rename must not
        break the link."""
        link = texts.thread_link(_Rec({"channel": "C0NEWCHAN1",
                                       "anchor_ts": "1790000000.111111"}))
        self.assertIn("/archives/C0NEWCHAN1/", link)
        self.assertIn("cid=C0NEWCHAN1", link)

    def test_missing_thread_returns_none_rather_than_a_broken_link(self):
        self.assertIsNone(texts.thread_link(_Rec({})))
        self.assertIsNone(texts.thread_link(_Rec({"channel": "C1"})))
        self.assertIsNone(texts.thread_link(_Rec({"anchor_ts": "1.2"})))

    def test_link_rides_in_the_ask(self):
        link = texts.thread_link(_Rec({"channel": "C0AUAS88FGW",
                                       "anchor_ts": "1787501632.308139"}))
        text = texts.compose(_Status("Willvim Marte"), "2026-09-07", link=link)
        self.assertIn(link, text)


class NoteJoiningTests(unittest.TestCase):
    def test_a_script_failure_never_hides_a_1to1_fallback(self):
        """Two different problems; the report must show both."""
        joined = texts._join_note("Messages chat list unreadable — sent 1:1",
                                  "SCRIPT MESSAGE NOT SENT: boom")
        self.assertIn("sent 1:1", joined)
        self.assertIn("SCRIPT MESSAGE NOT SENT", joined)

    def test_script_failure_alone_needs_no_separator(self):
        self.assertEqual(texts._join_note(None, "SCRIPT MESSAGE NOT SENT: x"),
                         "SCRIPT MESSAGE NOT SENT: x")


if __name__ == "__main__":
    unittest.main()
