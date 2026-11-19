"""Apex's answers belong to the office, not to Alphalete.

Megan, 2026-11-19: "this should be on the enrollment form so we can have them
enter in what is correct for them". Until then every office's people were
filed with Alphalete's position, pay basis, department -- and Alphalete's
STATE, on a tax record.

    python -m unittest automations.icd_onboarding.test_apex_settings
"""
import unittest

from automations.icd_onboarding import office_steps as OS


def _book(rows):
    """Stand in for the Office Settings tab."""
    return rows


class WhatAnOfficeHasAnswered(unittest.TestCase):

    def setUp(self):
        self._rows = OS._rows
        OS._rows = lambda book=None: book or []
        self.addCleanup(lambda: setattr(OS, "_rows", self._rows))

    def test_an_office_that_answered_gets_its_own_values(self):
        got = OS.apex_settings("vincent", book=_book([
            {OS.COL_OFFICE: "vincent", "State Working In": "Florida",
             "State Taxed In": "Florida", "Department": "400 Sales"}]))
        self.assertEqual(got["pay_state"], "Florida")
        self.assertEqual(got["tax_state"], "Florida")
        self.assertEqual(got["department"], "400 Sales")

    def test_a_column_left_blank_is_absent_not_empty(self):
        # Absent means "nobody said" and lets the default stand; an empty
        # string would blank a field Apex requires.
        got = OS.apex_settings("vincent", book=_book([
            {OS.COL_OFFICE: "vincent", "State Working In": "  ",
             "Position": "Sales Rep"}]))
        self.assertNotIn("pay_state", got)
        self.assertEqual(got["position"], "Sales Rep")

    def test_an_office_nobody_has_asked_answers_nothing(self):
        self.assertEqual(OS.apex_settings("cyrus", book=_book([])), {})

    def test_the_two_state_fields_are_reported_as_unanswered(self):
        unanswered = OS.apex_unanswered("cyrus", book=_book([]))
        self.assertEqual(sorted(unanswered), ["pay_state", "tax_state"])

    def test_answering_both_states_clears_the_block(self):
        rows = _book([{OS.COL_OFFICE: "cyrus", "State Working In": "Texas",
                       "State Taxed In": "Texas"}])
        self.assertEqual(OS.apex_unanswered("cyrus", book=rows), [])

    def test_answering_only_one_state_still_blocks_on_the_other(self):
        rows = _book([{OS.COL_OFFICE: "cyrus", "State Working In": "Texas"}])
        self.assertEqual(OS.apex_unanswered("cyrus", book=rows), ["tax_state"])

    def test_a_job_description_field_is_NOT_a_blocker(self):
        # Position being wrong is visible on the record. A state is not.
        rows = _book([{OS.COL_OFFICE: "cyrus", "State Working In": "Texas",
                       "State Taxed In": "Texas"}])
        self.assertNotIn("position", OS.apex_unanswered("cyrus", book=rows))

    def test_the_office_name_is_matched_regardless_of_case_and_spaces(self):
        rows = _book([{OS.COL_OFFICE: "  Vincent ",
                       "State Working In": "Florida"}])
        self.assertEqual(OS.apex_settings("VINCENT", book=rows)["pay_state"],
                         "Florida")

    def test_no_office_key_answers_nothing_rather_than_guessing(self):
        self.assertEqual(OS.apex_settings("", book=_book([])), {})


class WhatGetsTypedIntoApex(unittest.TestCase):
    """The overlay in values.plan_fill, checked at its own level."""

    def test_an_unanswered_state_is_dropped_not_defaulted(self):
        from automations.apex_new_starts import apex as AX
        # The constant is still Alphalete's -- that is the thing being guarded
        # against, so if this ever stops being Texas the guard is moot.
        self.assertEqual(AX.DEFAULTS["pay_state"], "Texas")
        self.assertEqual(AX.TAX_DEFAULTS["tax_state"], "Texas")


if __name__ == "__main__":
    unittest.main()
