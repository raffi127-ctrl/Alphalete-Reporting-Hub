"""The copy guard, and the lead-aware week gate.

The point of these is that this email CANNOT go out early while its body still
says "orientation today". The plumbing for a 2-day lead is in place (Megan,
2026-11-18); the words are hers to change, and until they do, turning the lead
up has to fail loudly rather than mail somebody the wrong day.

    python -m unittest automations.slack_skool_email.test_send_timing
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.slack_skool_email import config, run


class TheCopyGuard(unittest.TestCase):
    def test_todays_send_is_allowed(self):
        self.assertEqual(config.early_send_blocked_by_copy(0), "")

    def test_an_early_send_is_refused_while_the_body_says_today(self):
        why = config.early_send_blocked_by_copy(2)
        self.assertTrue(why)
        self.assertIn("orientation today", why)
        # It has to say what to DO, not just that it refused.
        self.assertIn("config.py", why)

    def test_the_refusal_names_every_day_of_phrase_it_found(self):
        why = config.early_send_blocked_by_copy(2)
        for phrase in config.DAY_OF_PHRASES:
            self.assertIn(phrase, why, "%r not named" % phrase)

    def test_the_phrases_it_guards_are_really_in_the_body(self):
        # A guard watching for words that aren't there would pass forever and
        # protect nothing.
        for phrase in config.DAY_OF_PHRASES:
            self.assertIn(phrase.lower(), config.BODY.lower())

    def test_reworded_copy_would_let_the_lead_through(self):
        # Proves the guard is about the WORDS and not a blanket "no early
        # sends" -- so Megan rewording that line is all it takes.
        real = config.BODY
        try:
            config.BODY = ("Welcome to Alphalete Marketing!\n\nBefore your "
                           "first day, please download these three apps.")
            self.assertEqual(config.early_send_blocked_by_copy(2), "")
        finally:
            config.BODY = real

    def test_the_lead_is_still_off(self):
        # If this fails, somebody turned it on -- which is fine, but it should
        # be a decision somebody made, with the copy fixed first.
        self.assertEqual(config.SEND_LEAD_DAYS, 0)


class TheWeekGate(unittest.TestCase):
    """`_wrong_week` with a lead: still refuses last week's tab."""

    def test_todays_tab_is_fine(self):
        self.assertIsNone(run._wrong_week("D2D OBCL 11.23",
                                          today=dt.date(2026, 11, 23)))

    def test_last_weeks_tab_is_still_refused(self):
        # The fault this gate exists for: mailing fifty-two people who started
        # a week ago "we're excited to have you at orientation today".
        why = run._wrong_week("D2D OBCL 11.16", today=dt.date(2026, 11, 23))
        self.assertTrue(why)
        self.assertIn("hasn't been built yet", why)

    def test_next_weeks_tab_is_refused_while_the_lead_is_zero(self):
        self.assertTrue(run._wrong_week("D2D OBCL 11.23",
                                        today=dt.date(2026, 11, 21)))

    def test_next_weeks_tab_is_allowed_once_a_lead_is_set(self):
        real = config.SEND_LEAD_DAYS
        try:
            config.SEND_LEAD_DAYS = 2
            self.assertIsNone(run._wrong_week("D2D OBCL 11.23",
                                              today=dt.date(2026, 11, 21)))
            # Three days out is past the lead, so still refused.
            self.assertTrue(run._wrong_week("D2D OBCL 11.23",
                                            today=dt.date(2026, 11, 20)))
        finally:
            config.SEND_LEAD_DAYS = real

    def test_a_lead_never_opens_the_gate_backwards(self):
        real = config.SEND_LEAD_DAYS
        try:
            config.SEND_LEAD_DAYS = 2
            self.assertTrue(run._wrong_week("D2D OBCL 11.16",
                                            today=dt.date(2026, 11, 23)))
        finally:
            config.SEND_LEAD_DAYS = real

    def test_an_unreadable_tab_name_is_refused(self):
        why = run._wrong_week("Sheet1", today=dt.date(2026, 11, 23))
        self.assertIn("can't read a date", why)


if __name__ == "__main__":
    unittest.main()
