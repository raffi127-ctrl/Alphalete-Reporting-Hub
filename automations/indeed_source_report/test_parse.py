"""The noise filter must not eat real applicants.

Indeed forwards an application as "[Action required] New application for <ad
title>". NOISE carries an `action required` rule written for Indeed's BILLING
mail, and it matched those subjects too — so every wrapped applicant was thrown
away before it could be counted. 635 of them in the 2026-08-27 run.

The two halves of the fix are both load-bearing, so both are tested here: the
wrapper comes OFF (the applicant is kept, filed under the ad title underneath),
and real billing mail still gets JUNKED.
"""
import unittest

from automations.indeed_source_report import parse


def _survives(subject):
    """True if this subject would reach the ad table (mirrors load_table)."""
    s = parse.WRAPPER.sub('', subject)
    return not parse.NOISE.search(s)


class TheWrappedApplicantIsKept(unittest.TestCase):

    def test_a_wrapped_application_survives(self):
        self.assertTrue(_survives(
            "[Action required] New application for Sales Rep - Dallas"))

    def test_the_ad_title_is_what_is_left(self):
        self.assertEqual(
            parse.WRAPPER.sub('', "[Action required] New application for "
                                  "Entry Level Marketing"),
            "Entry Level Marketing")

    def test_casing_and_a_colon_separator_still_match(self):
        """Indeed is not consistent about either."""
        self.assertEqual(
            parse.WRAPPER.sub('', "[Action Required] New Application For: "
                                  "Door to Door Sales"),
            "Door to Door Sales")

    def test_one_regex_not_two(self):
        """ad_sales_board used to carry its own copy. Two would drift, and the
        drifted one would quietly start junking applicants again."""
        from automations.ad_sales_board import names
        self.assertIs(names.WRAPPER, parse.WRAPPER)


class RealBillingMailIsStillJunked(unittest.TestCase):
    """The `action required` rule exists for a reason — don't widen the hole."""

    def test_payment_mail_is_junked(self):
        self.assertFalse(_survives(
            "[Action required] Update your payment method"))

    def test_invoice_mail_is_junked(self):
        self.assertFalse(_survives("Action required: your invoice is due"))

    def test_a_bare_action_required_subject_is_junked(self):
        self.assertFalse(_survives("[Action required] Verify your account"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
