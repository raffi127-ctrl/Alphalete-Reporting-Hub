"""Matching rules for the commission run. Pure/offline — no sheet access.

Each case here is a real spelling seen in the 2026-08-30 data (Loom
2026-09-03); they are the ones that would silently pay the wrong person.

    python -m unittest automations.commission_sheet.test_names
"""
import unittest

from automations.commission_sheet.names import (
    customer_key, customer_keys, header_index, match_person, spm_key)


class SpmKey(unittest.TestCase):
    def test_formats_of_the_same_order_agree(self):
        for raw in ("SPM267681157", "267681157", "spm 267 681 157"):
            self.assertEqual(spm_key(raw), "267681157", raw)

    def test_junk_yields_no_key(self):
        # People type these into the form's SPM box; none may match an order.
        for raw in ("N/a", "N/A", "F", "ENERGY SALE", "", None, "12345"):
            self.assertEqual(spm_key(raw), "", repr(raw))


class CustomerKeys(unittest.TestCase):
    def test_order_log_abbreviation_meets_the_full_name(self):
        # The order log files this customer under the FIRST surname token.
        self.assertTrue(customer_keys("JAXEL Lopez SEPULVEDA")
                        & customer_keys("JAXEL L"))
        self.assertTrue(customer_keys("EDUARDO ORTIZ ADASME")
                        & customer_keys("EDUARDO O"))
        self.assertTrue(customer_keys("LINDA FUENTES") & customer_keys("LINDA F"))

    def test_different_customers_do_not_collide(self):
        self.assertFalse(customer_keys("JOSE REYES") & customer_keys("GENOVEVA M"))
        self.assertFalse(customer_keys("NEZARINA F") & customer_keys("NAEEM A"))

    def test_canonical_key_is_first_plus_last_initial(self):
        self.assertEqual(customer_key("LINDA FUENTES"), "linda f")
        self.assertEqual(customer_key("barry h"), "barry h")
        self.assertEqual(customer_key(""), "")


class MatchPerson(unittest.TestCase):
    ROSTER = ["Joshua Mascorro", "Zoria Johnson", "Pranish Shrestha",
              "Ana Griffin", "Chloe Johnson", "Keegan Miller"]

    def test_nickname_resolves_via_surname(self):
        self.assertEqual(match_person("JD Mascorro", self.ROSTER)[0],
                         "Joshua Mascorro")

    def test_first_name_only_resolves_when_unique(self):
        self.assertEqual(match_person("Zoria", self.ROSTER)[0], "Zoria Johnson")

    def test_misspelling_resolves(self):
        self.assertEqual(match_person("Pranish Shreshta", self.ROSTER)[0],
                         "Pranish Shrestha")

    def test_trailing_space_and_case_resolve(self):
        self.assertEqual(match_person("ana griffin ", self.ROSTER)[0],
                         "Ana Griffin")

    def test_ambiguity_returns_candidates_not_a_guess(self):
        # Two Johnsons: guessing here pays the wrong rep.
        match, cands = match_person("Johnson", self.ROSTER)
        self.assertIsNone(match)
        self.assertIn("Zoria Johnson", cands)
        self.assertIn("Chloe Johnson", cands)

    def test_stranger_does_not_match(self):
        # Keadan Sutton really is absent from the 8/30 roster.
        self.assertIsNone(match_person("Keadan Sutton", self.ROSTER)[0])

    def test_empty_inputs(self):
        self.assertEqual(match_person("", self.ROSTER), (None, []))
        self.assertEqual(match_person("Zoria", []), (None, []))


class HeaderIndex(unittest.TestCase):
    HEADERS = ["Timestamp", "﻿Your Name (That's getting the credit?)",
               "Name that the Sale is under", "Customers Name", "SPM #", "Status"]

    def test_exact_and_substring(self):
        self.assertEqual(header_index(self.HEADERS, "Timestamp"), 0)
        self.assertEqual(header_index(self.HEADERS, "Your Name"), 1)
        self.assertEqual(header_index(self.HEADERS, "SPM #"), 4)

    def test_missing_column_names_the_headers(self):
        with self.assertRaises(KeyError) as e:
            header_index(self.HEADERS, "spe.Name")
        self.assertIn("Timestamp", str(e.exception))

    def test_ambiguous_column_refuses(self):
        with self.assertRaises(KeyError):
            header_index(["Rep Name", "Rep Number"], "Rep")


if __name__ == "__main__":
    unittest.main()
