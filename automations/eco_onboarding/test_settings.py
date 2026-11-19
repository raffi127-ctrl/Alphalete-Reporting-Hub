"""The LucyECO Onboarding enrolment: what it asks, and what it writes.

The failure these exist for (2026-11-19): `Blue Ink` and `Rate of Pay` were
read by the onboarding board and ABSENT from the `Office Settings` tab, so
`rate_of_pay()` returned None for every office and every non-Raf person was
held back on a question nobody could answer. A form that creates its own
columns is the fix; these pin the parts that would make it silent again.

    python -m unittest automations.eco_onboarding.test_settings
"""
import unittest

from automations.eco_onboarding import settings as S
from automations.eco_onboarding import store
from automations.icd_onboarding import office_steps as OS


class WhatItAsks(unittest.TestCase):

    def test_it_asks_for_everything_apex_reads(self):
        asked = {q.field for q in S.ALL}
        for field in OS.APEX_COLUMNS:
            self.assertIn(field, asked, "Apex reads %r and nobody asks" % field)

    def test_it_asks_for_the_two_columns_the_board_reads(self):
        columns = {q.column for q in S.ALL}
        self.assertIn(OS.COL_BLUEINK, columns)
        self.assertIn(OS.COL_RATE, columns)

    def test_sterling_is_on_the_form(self):
        columns = {q.column for q in S.ALL}
        self.assertIn("State", columns)
        self.assertIn("City", columns)

    def test_the_must_ask_fields_are_required_on_the_form(self):
        by_field = {q.field: q for q in S.ALL}
        for field in OS.APEX_MUST_ASK:
            self.assertTrue(by_field[field].required,
                            "%s blocks a person, so it cannot be optional" % field)

    def test_a_state_can_only_be_one_sterling_accepts(self):
        by_field = {q.field: q for q in S.ALL}
        for field in ("state", "pay_state", "tax_state"):
            self.assertIn("Texas", by_field[field].choices)
            self.assertIn("Florida", by_field[field].choices)


class WhatCountsAsAnswered(unittest.TestCase):

    GOOD = {"state": "Florida", "city": "Tampa", "blue_ink": "Yes",
            "rate": "12.50", "pay_state": "Florida", "tax_state": "Florida"}

    def test_a_complete_answer_has_no_problems(self):
        self.assertEqual(S.problems(dict(self.GOOD)), [])

    def test_a_missing_tax_state_is_named_in_the_owners_words(self):
        a = dict(self.GOOD); a.pop("tax_state")
        said = S.problems(a)
        self.assertEqual(len(said), 1)
        self.assertIn("TAXED", said[0])

    def test_a_rate_that_is_not_a_number_is_caught(self):
        a = dict(self.GOOD); a["rate"] = "ten dollars"
        self.assertTrue(any("numbers only" in p for p in S.problems(a)))

    def test_a_rate_of_zero_is_caught(self):
        a = dict(self.GOOD); a["rate"] = "0"
        self.assertTrue(any("more than 0" in p for p in S.problems(a)))

    def test_a_dollar_sign_is_accepted(self):
        a = dict(self.GOOD); a["rate"] = "$12.50"
        self.assertEqual(S.problems(a), [])


class WhatItWrites(unittest.TestCase):

    def test_an_unanswered_field_is_absent_not_blank(self):
        # Blank would turn somebody's existing answer back into a question.
        row = S.row_for({"state": "Texas"}, "megan", "now")
        self.assertEqual(row.get("State"), "Texas")
        self.assertNotIn("City", row)
        self.assertNotIn(OS.COL_RATE, row)

    def test_it_stamps_who_and_when(self):
        row = S.row_for({}, "megan", "11/19/2026 14:00:00")
        self.assertEqual(row[S.COL_UPDATED_BY], "megan")
        self.assertEqual(row[S.COL_UPDATED_AT], "11/19/2026 14:00:00")

    def test_the_columns_the_live_tab_was_missing_are_reported(self):
        # The real headers on 2026-11-19, verbatim.
        live = ["Office", "State", "City", "Updated By", "Updated At",
                "AppStream", "Approved Accounts", "", "Owner",
                "Onboarding Sheet"]
        missing = S.missing_columns(live)
        self.assertIn(OS.COL_BLUEINK, missing)
        self.assertIn(OS.COL_RATE, missing)
        self.assertIn("State Taxed In", missing)
        # ...and the ones it already had are NOT re-added.
        self.assertNotIn("State", missing)
        self.assertNotIn("City", missing)

    def test_nothing_is_missing_once_the_form_has_run(self):
        live = ["Office"] + S.columns_needed()
        self.assertEqual(S.missing_columns(live), [])


class TheSpreadsheetColumnLetters(unittest.TestCase):

    def test_it_counts_past_z(self):
        self.assertEqual([store._a1(n) for n in (1, 26, 27, 52, 53)],
                         ["A", "Z", "AA", "AZ", "BA"])


if __name__ == "__main__":
    unittest.main()
