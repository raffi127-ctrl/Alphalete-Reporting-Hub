"""The payroll notification's wording, and who it tags. Offline — no Slack.

    python -m unittest automations.commission_sheet.test_notify
"""
import datetime as dt
import unittest

from automations.commission_sheet.notify import (
    NOTIFY, _approver_of, _last_sunday, reply_for, title_for, week_label)


class Wording(unittest.TestCase):
    def test_week_label_is_zero_padded(self):
        # Megan's wording is WE MM/DD/YY — padded, unlike the RH 9.6.26 filename.
        self.assertEqual(week_label(dt.date(2026, 9, 6)), "09/06/26")
        self.assertEqual(week_label(dt.date(2026, 12, 27)), "12/27/26")

    def test_title_is_exactly_what_was_asked_for(self):
        self.assertEqual(
            title_for(dt.date(2026, 9, 6)),
            "Payroll Commission Processing Ready for Review WE 09/06/26")

    def test_reply_tags_jd_and_carries_the_link(self):
        reply = reply_for("SHEETID123")
        self.assertIn("<@U05094TTPKQ>", reply)
        self.assertIn("https://docs.google.com/spreadsheets/d/SHEETID123/edit",
                      reply)

    def test_the_other_jd_account_is_never_tagged(self):
        # Two "JD Mascorro" accounts exist; U068T4LA0C8 is the wrong one.
        self.assertNotIn("U068T4LA0C8", reply_for("X"))
        self.assertEqual(list(NOTIFY), ["U05094TTPKQ"])


class TickReading(unittest.TestCase):
    """Reads whether JD ticked the post. Gates nothing today — see notify.py."""

    def test_tick_from_jd_is_recognised(self):
        msg = {"reactions": [{"name": "white_check_mark",
                              "users": ["U05094TTPKQ"], "count": 1}]}
        self.assertEqual(_approver_of(msg), ("U05094TTPKQ", "JD Mascorro"))

    def test_any_of_slacks_ticks_counts(self):
        for name in ("heavy_check_mark", "ballot_box_with_check", "check"):
            msg = {"reactions": [{"name": name, "users": ["U05094TTPKQ"]}]}
            self.assertIsNotNone(_approver_of(msg), name)

    def test_tick_from_someone_else_does_not_count(self):
        msg = {"reactions": [{"name": "white_check_mark",
                              "users": ["U088E2KJEV8", "U045Z8N0ZQC"]}]}
        self.assertIsNone(_approver_of(msg))

    def test_a_thumbs_up_from_jd_does_not_count(self):
        msg = {"reactions": [{"name": "+1", "users": ["U05094TTPKQ"]}]}
        self.assertIsNone(_approver_of(msg))

    def test_no_reactions(self):
        self.assertIsNone(_approver_of({}))
        self.assertIsNone(_approver_of({"reactions": []}))


class DefaultWeek(unittest.TestCase):
    def test_sunday_is_its_own_week_ending(self):
        self.assertEqual(_last_sunday(dt.date(2026, 9, 6)), dt.date(2026, 9, 6))

    def test_midweek_looks_back_to_the_sunday_just_gone(self):
        for day in range(7, 13):                       # Mon 7th .. Sat 12th
            self.assertEqual(_last_sunday(dt.date(2026, 9, day)),
                             dt.date(2026, 9, 6), f"Sep {day}")


if __name__ == "__main__":
    unittest.main()
