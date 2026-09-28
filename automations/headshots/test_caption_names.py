"""The caption IS the name — what counts as one, and what stays a question.

    python -m unittest automations.headshots.test_caption_names
"""
import unittest

from automations.headshots.run import name_from_caption as f


class HyphenatedSurnames(unittest.TestCase):
    """JD, 2026-09-28: "I think it's broken cause the guy has a hyphen."
    "Damarrion Hawkins - Brown" read as 4 words, one of them a bare "-", so
    the bot asked who it was about a caption that named him. The OBCL spells
    them this way too ("Manuel Quiroz - Lebron"), so it is house style."""

    def test_spaced_hyphen_is_a_name(self):
        self.assertEqual(f("Damarrion Hawkins - Brown"),
                         "Damarrion Hawkins-Brown")

    def test_tight_hyphen_still_works(self):
        self.assertEqual(f("Damarrion Hawkins-Brown"),
                         "Damarrion Hawkins-Brown")

    def test_hyphenated_first_name(self):
        self.assertEqual(f("Mary-Kate Olsen"), "Mary-Kate Olsen")

    def test_an_em_dash_reads_the_same(self):
        self.assertEqual(f("Manuel Quiroz — Lebron"), "Manuel Quiroz-Lebron")


class StillNotNames(unittest.TestCase):
    """Joining hyphens must not turn chatter into a person."""

    def test_a_dash_after_chatter_is_still_a_question(self):
        self.assertIsNone(f("headshot - John Smith"))

    def test_plain_chatter(self):
        self.assertIsNone(f("photo for the new hire"))
        self.assertIsNone(f("headshots pls"))

    def test_one_word_is_not_enough(self):
        self.assertIsNone(f("Damarrion"))


class OrdinaryNames(unittest.TestCase):
    def test_apostrophe(self):
        self.assertEqual(f("Le'derius Arnold"), "Le'derius Arnold")

    def test_extra_spaces(self):
        self.assertEqual(f("Ana  Griffin"), "Ana Griffin")


if __name__ == "__main__":
    unittest.main()
