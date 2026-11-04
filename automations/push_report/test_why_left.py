"""Each hourly line says why the ones left were not pushed (Megan 2026-11-04)."""
import datetime as dt
import unittest

from automations.push_report import run as PR


class WhyLeft(unittest.TestCase):
    def test_reasons_in_plain_words_with_the_rest_not_reached(self):
        s = {"end": 7, "unconfirmed": 2,
             "why_left": {"no_number": 2, "indeed": 1, "unstuck": 2}}
        self.assertEqual(PR.why_left_text(s),
                         "1 waiting on Indeed's check, 2 no phone number "
                         "anywhere, 2 not reached yet")

    def test_line_carries_the_why(self):
        s = {"live": True, "sent_today": 33, "end": 7, "walled": True,
             "unconfirmed": 2,
             "why_left": {"indeed": 4, "no_number": 1, "unstuck": 2}}
        line = PR._relay_line("Raf 24065", s, dt.datetime(2026, 11, 4, 10, 58))
        self.assertEqual(line, "Raf 24065 (his computer): 33 pushed · 7 left @ "
                         "10:58 AM · Indeed check up · :warning: 2 didn't stick"
                         " · why: 4 waiting on Indeed's check, 1 no phone "
                         "number anywhere")

    def test_old_computers_without_reasons_look_like_before(self):
        s = {"live": True, "sent_today": 3, "end": 4}
        self.assertNotIn("why", PR._relay_line("Carlos 11580", s, None))

    def test_empty_queue_says_no_why(self):
        s = {"live": True, "sent_today": 3, "end": 0, "why_left": {"no_number": 2}}
        self.assertNotIn("why", PR._relay_line("Carlos 11580", s, None))


if __name__ == "__main__":
    unittest.main()
