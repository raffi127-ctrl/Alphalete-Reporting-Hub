"""Which spellings are one person, and which refusals must survive.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.digi_docs.test_namematch

The cost of a wrong match here is a real person receiving somebody else's
contract, so the interesting tests are the ones that REFUSE.
"""
from __future__ import annotations

import unittest

from automations.digi_docs import namematch as nm

DIRECTORY = [
    "Lederius Arnold", "Abel Quinones", "Courtney Green", "Julian Rodriguez",
    "Juliet Rodriguez", "Carlos Reyes", "William Garvin", "Ana Olalde",
]


class SpellingNoiseIsNotADifferentPerson(unittest.TestCase):

    def test_an_apostrophe(self):
        self.assertEqual(("Lederius Arnold", "strict"),
                         nm.resolve("Le'derius Arnold", DIRECTORY))

    def test_an_accent(self):
        """ñ -> n. The strict rule never matched Quiñones to Quinones."""
        self.assertEqual(("Abel Quinones", "strict"),
                         nm.resolve("Abel Quiñones", DIRECTORY))

    def test_a_near_miss_first_name_with_a_unique_surname(self):
        self.assertEqual(("Courtney Green", "near-miss"),
                         nm.resolve("Cortney Green", DIRECTORY))

    def test_an_exact_match_is_still_strict(self):
        self.assertEqual(("Ana Olalde", "strict"),
                         nm.resolve("Ana Olalde", DIRECTORY))


class RefusalsThatMustSurvive(unittest.TestCase):

    def test_two_people_share_the_surname(self):
        """Julian and Juliet Rodriguez, 2026-09-14. Two surname-mates refuse
        however the first names look — this is the case the strict rule was
        built for and widening must not reach it."""
        self.assertEqual((None, ""), nm.resolve("Juliet Rodriguez", DIRECTORY))

    def test_a_shared_surname_and_a_different_person(self):
        """Angelina Reyes is not Carlos Reyes. A unique surname is necessary,
        not sufficient — the first names still have to resemble each other."""
        self.assertEqual((None, ""), nm.resolve("Angelina Reyes", DIRECTORY))

    def test_a_nickname_is_not_a_resemblance(self):
        """Billy IS William, and no letter-ratio can know that. There is no
        cutoff that matches Billy/William without also matching people who are
        not each other, so this refuses and the fact goes in the ICD Aliases
        sheet instead."""
        self.assertEqual((None, ""), nm.resolve("Billy Garvin", DIRECTORY))

    def test_a_name_nobody_in_the_directory_has(self):
        self.assertEqual((None, ""), nm.resolve("Quadarius Tarrio", DIRECTORY))

    def test_an_empty_directory(self):
        self.assertEqual((None, ""), nm.resolve("Ana Olalde", []))

    def test_a_blank_name(self):
        self.assertEqual((None, ""), nm.resolve("", DIRECTORY))


class TheRatioIsWhereItIs(unittest.TestCase):
    """Pinning the cutoff, since both neighbours matter."""

    def test_cortney_courtney_is_above_it(self):
        self.assertGreaterEqual(
            nm.difflib.SequenceMatcher(None, "cortney", "courtney").ratio(),
            nm.FIRST_NAME_RATIO)

    def test_billy_william_is_below_it(self):
        self.assertLess(
            nm.difflib.SequenceMatcher(None, "billy", "william").ratio(),
            nm.FIRST_NAME_RATIO)


if __name__ == "__main__":
    unittest.main()
