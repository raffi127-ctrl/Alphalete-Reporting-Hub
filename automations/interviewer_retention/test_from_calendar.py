"""Pure tests for from_calendar.py (the rules proven on 11280, 2026-11-24).

    python -m unittest automations.interviewer_retention.test_from_calendar
"""
import unittest

from automations.interviewer_retention import boxes as bx
from automations.interviewer_retention import from_calendar as fc


class Names(unittest.TestCase):
    def setUp(self):
        self.names = fc.load_names("11280")

    def test_full_name_to_ars_name_ignoring_accents_and_case(self):
        self.assertEqual(fc.interviewer("Gabriela Munoz Toro", self.names), "Gabriela MT")
        self.assertEqual(fc.interviewer("maria victoria ferrero", self.names), "Mavi")

    def test_none_is_the_owner(self):
        self.assertEqual(fc.interviewer("None", self.names), "Owner")
        self.assertEqual(fc.interviewer("", self.names), "Owner")

    def test_unknown_name_is_flagged_never_guessed(self):
        with self.assertRaises(fc.UnknownInterviewer):
            fc.interviewer("Victoria Gomez", self.names)


class FirstRound(unittest.TestCase):
    def test_outcomes(self):
        self.assertEqual(fc.first_round("radio1", "Disqualified (11-24)", ""), (bx.DISQUALIFY, "", ""))
        self.assertEqual(fc.first_round("radio1", "Declined (11-24)", "Declined Next Round"),
                         (bx.DECLINED, "", ""))
        self.assertIsNone(fc.first_round("radio2", "Reschedule 1st Pause", "Left Message"))

    def test_invite_call(self):
        self.assertEqual(fc.first_round("2nd On Nov 25", "Assigned 2nd", "Invite to next – Booked"),
                         (bx.QUALIFY, bx.ANSWERED, bx.BOOKED))
        self.assertEqual(fc.first_round("radio1", "Schedule 2nd", "Declined Next Round"),
                         (bx.QUALIFY, bx.ANSWERED, "Not Booked"))
        self.assertEqual(fc.first_round("radio1", "Schedule 2nd", "Invite to next – SMS sent"),
                         (bx.QUALIFY, bx.NO_ANSWER, ""))

    def test_no_invite_status_is_left_blank_like_the_sheet(self):
        self.assertEqual(fc.first_round("radio1", "Schedule 2nd", ""), (bx.QUALIFY, "", ""))


class SecondRound(unittest.TestCase):
    def test_offer_dropdown_means_showed_even_when_leader_said_no(self):
        self.assertEqual(fc.second_round(True, "Rejected or Not qualified"), bx.SHOWED)

    def test_no_show_split_by_follow_up_status(self):
        self.assertEqual(fc.second_round(False, "Rescheduled Requested"), bx.RESCHEDULE)
        self.assertEqual(fc.second_round(False, "Cancelled"), bx.CANCELLED)
        self.assertEqual(fc.second_round(False, "Called"), bx.NO_SHOW)


if __name__ == "__main__":
    unittest.main()
