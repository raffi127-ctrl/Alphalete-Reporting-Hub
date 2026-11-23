"""The note that says we re-sent their documents."""
from __future__ import annotations

import unittest
from unittest import mock

from automations.blueink_docs import chase_email as CE


class WhatItSays(unittest.TestCase):

    def test_both_reminders_say_we_have_just_re_sent_it(self):
        """The whole reason this exists. Blue Ink's remind carries no message
        of ours, so its email looks exactly like the first one -- and somebody
        who has been meaning to get to it reads a duplicate and ignores it."""
        for kind in ("day_before", "morning_of"):
            body = CE.build("Jerry Esebanme", "j@x.com", kind).get_content()
            self.assertIn("re-sent", body, kind)
            self.assertIn("BlueInk", body, kind)

    def test_it_tells_them_where_to_look_when_it_is_not_there(self):
        for kind in ("day_before", "morning_of"):
            body = CE.build("Jerry", "j@x.com", kind).get_content()
            self.assertIn("spam", body, kind)

    def test_the_two_days_do_not_say_the_same_thing(self):
        a = CE.build("Jerry", "j@x.com", "day_before").get_content()
        b = CE.build("Jerry", "j@x.com", "morning_of").get_content()
        self.assertIn("tomorrow", a)
        self.assertIn("today", b)
        self.assertNotEqual(a, b)

    def test_it_carries_no_link_of_its_own(self):
        """The only working link is inside Blue Ink's email, tied to their
        packet. Anything we pasted would be that link copied -- wrong the
        moment a packet is re-issued -- or a sign-in they have no account
        for."""
        for kind in ("day_before", "morning_of"):
            body = CE.build("Jerry", "j@x.com", kind).get_content()
            self.assertNotIn("http", body, kind)

    def test_a_missing_name_is_not_an_empty_greeting(self):
        self.assertEqual(CE.first_name(""), "there")
        self.assertEqual(CE.first_name("   "), "there")
        self.assertEqual(CE.first_name("Esebanme, Jerry"), "Esebanme")
        self.assertEqual(CE.first_name("Cher"), "Cher")

    def test_an_unknown_kind_is_refused_rather_than_guessed(self):
        self.assertRaises(ValueError, CE.build, "Jerry", "j@x.com", "someday")


class WhenItSends(unittest.TestCase):

    def test_a_dry_run_sends_nothing(self):
        with mock.patch("automations.slack_skool_email.gmail_reception.send") as s:
            said = CE.send("Jerry", "j@x.com", "day_before", really=False)
        s.assert_not_called()
        self.assertEqual(said, "would email")

    def test_no_address_is_said_rather_than_crashed(self):
        self.assertEqual(CE.send("Jerry", "", "day_before", really=True),
                         "no email address")

    def test_a_mail_failure_never_raises_into_the_chase(self):
        """The resend has already happened by the time this runs. A mail
        error that propagated would make the chase report the resend as
        failed -- and somebody re-runs it, and a person gets two of
        everything."""
        with mock.patch("automations.slack_skool_email.gmail_reception.assert_right_mailbox",
                        side_effect=RuntimeError("wrong mailbox")):
            said = CE.send("Jerry", "j@x.com", "day_before", really=True,
                           log=lambda *_a: None)
        self.assertIn("email failed", said)

    def test_it_goes_from_receptions_mailbox(self):
        """The address they already reply to, and where a reply about
        paperwork should land."""
        sent = {}
        with mock.patch("automations.slack_skool_email.gmail_reception.assert_right_mailbox"), \
             mock.patch("automations.slack_skool_email.gmail_reception.send",
                        side_effect=lambda m: sent.update({"to": m["To"]})):
            said = CE.send("Jerry", "j@x.com", "morning_of", really=True)
        self.assertEqual(said, "emailed")
        self.assertEqual(sent["to"], "j@x.com")


class WhereTheChaseCallsIt(unittest.TestCase):

    def test_the_email_goes_after_the_resend_and_only_if_it_worked(self):
        import inspect
        from automations.blueink_docs import chase
        src = inspect.getsource(chase.run)
        remind = src.index("BI.remind_packet(key)")
        failed = src.index('log("    %-28s FAILED')
        emailed = src.index("really=True")
        self.assertLess(remind, emailed,
                        "the email claims a resend before it has happened")
        self.assertLess(failed, emailed,
                        "a failed resend must return before the email goes")


if __name__ == "__main__":
    unittest.main()
