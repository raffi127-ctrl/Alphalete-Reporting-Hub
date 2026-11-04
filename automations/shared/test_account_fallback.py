"""A misspelled onboarded name falls back to its ownerville account number.

2026-10-26: Omar's first 9 PM knock board died on "Couldn't impersonate 'Omar
Mohammad' in ownerville: name not found" — ownerville spells him "Omar
Mohamad", and his onboarding row already carried ov_account 24153. Drew (9/28)
and Jairo (9/29) failed their first 9 PM the same way. The number is the
fallback, and the identity check must accept it.
"""
import unittest
from unittest import mock

from automations.shared import ownerville_office_pins as P
from automations.rashad_metrics import knocks_pull as KP
from automations.rashad_metrics.test_impersonation_assert import _Page

ROWS = [
    {"owner": "Omar Mohammad", "knocks_office": "Omar Mohammad",
     "ov_account": "24153"},
    {"owner": "Eveliz Wright", "knocks_office": "Eveliz Wright",
     "ov_account": ""},
    # one name, two numbers -> no guess
    {"owner": "Two Offices", "ov_account": "111"},
    {"owner": "Two Offices", "ov_account": "222"},
    {"owner": "Float Acct", "ov_account": "22162.0"},
]


class AccountFallback(unittest.TestCase):
    def setUp(self):
        self.fb = P._load_fallback(ROWS)

    def test_onboarded_name_maps_to_its_number(self):
        self.assertEqual(self.fb["omar mohammad"], "24153")

    def test_no_account_no_fallback(self):
        self.assertNotIn("eveliz wright", self.fb)

    def test_ambiguous_name_is_dropped(self):
        self.assertNotIn("two offices", self.fb)

    def test_spreadsheet_float_keeps_its_digits(self):
        self.assertEqual(self.fb["float acct"], "22162")

    def test_real_files_carry_omar(self):
        P._FALLBACK = None
        self.assertEqual(P.account_fallback("Omar Mohamad"), "24153")


class IdentityAcceptsTheNumber(unittest.TestCase):
    def test_label_on_the_onboarded_number_passes(self):
        page = _Page("Omar Mohamad (24153 - Kalkan Marketing)")
        with mock.patch.object(P, "_FALLBACK", {"omar mohammad": "24153"}):
            KP.assert_impersonating(page, "RQ", "Omar Mohammad", {},
                                    verbose=False)

    def test_another_office_still_raises(self):
        page = _Page("Calvin Ribera (22162 - Vernon, Inc.)")
        with mock.patch.object(P, "_FALLBACK", {"omar mohammad": "24153"}):
            with self.assertRaises(RuntimeError):
                KP.assert_impersonating(page, "RQ", "Omar Mohammad", {},
                                        verbose=False)


if __name__ == "__main__":
    unittest.main()
