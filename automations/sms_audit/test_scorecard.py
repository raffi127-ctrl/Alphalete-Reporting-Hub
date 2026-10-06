# -*- coding: utf-8 -*-
"""Scorecard: name folding, the red mark, and the week-over-week shading.

Run: python -m unittest automations.sms_audit.test_scorecard
"""
import unittest

from automations.sms_audit import scorecard as S


class Names(unittest.TestCase):
    """Bookings say "L. Robinson", texts say "Leticia Robinson"."""

    def test_short_and_long_spelling_fold_together(self):
        self.assertEqual(S.key_of("L. Robinson"), S.key_of("Leticia Robinson"))
        self.assertEqual(S.key_of("A. Ceron"), S.key_of("Aisha Ceron"))

    def test_a_team_tag_is_not_a_surname(self):
        """Three people once shared the key 'a.apt'."""
        self.assertEqual(S.key_of("A. Zelaya APT"),
                         S.key_of("Anthony Zelaya APT"))
        self.assertNotEqual(S.key_of("Anthony Zelaya APT"),
                            S.key_of("Abdiel Amador APT"))
        self.assertNotEqual(S.key_of("Max Jimenez APT"),
                            S.key_of("Dulce Lamb APT"))

    def test_a_two_word_tag_name_still_pairs(self):
        """Stripping NLR from 'C. NLR' would leave nothing to match on."""
        self.assertEqual(S.key_of("C. NLR"), S.key_of("Caitlyn NLR"))

    def test_different_people_stay_apart(self):
        self.assertNotEqual(S.key_of("Jorge Pena"), S.key_of("Dani Pena"))

    def test_blank_is_no_key(self):
        self.assertEqual(S.key_of(""), "")
        self.assertEqual(S.key_of(None), "")

    def test_the_ai_is_recognised_either_way(self):
        self.assertTrue(S.is_ai("AI Messaging"))
        self.assertTrue(S.is_ai("A. Messaging"))
        self.assertFalse(S.is_ai("Aisha Ceron"))


class Mark(unittest.TestCase):
    """Megan: show exactly what was sent, with the bad part in red."""

    def test_the_offending_phrase_is_wrapped(self):
        got = S.mark("Also, it is a weekly base pay.", "base pay")
        self.assertIn("<span class='bad'>base pay</span>", got)
        self.assertIn("Also, it is a weekly", got)

    def test_the_whole_message_survives(self):
        body = "Our location is 3100 Premier Dr, Irving, TX 75063, USA"
        got = S.mark(body, "3100 Premier Dr, Irving, TX 75063, USA")
        self.assertIn("Our location is", got)

    def test_matching_ignores_case(self):
        got = S.mark("Our LOcation is 3100 Premier Dr", "3100 premier dr")
        self.assertIn("<span class='bad'>3100 Premier Dr</span>", got)

    def test_an_applicant_question_is_shown_not_highlighted(self):
        got = S.mark("The Hiring Manager can answer that in detail.",
                     "they asked: is this remote?")
        self.assertIn("They asked: is this remote?", got)
        self.assertIn("class='bad'", got)      # the deflection itself is marked

    def test_html_in_a_message_is_escaped(self):
        got = S.mark("call <b>now</b> & ask", "")
        self.assertIn("&lt;b&gt;", got)
        self.assertNotIn("<b>now</b>", got)

    def test_no_hit_and_no_deflection_leaves_it_plain(self):
        self.assertEqual(S.mark("See you at 9.", ""), "See you at 9.")


class Shade(unittest.TestCase):
    def test_best_week_is_green_and_worst_is_red(self):
        vals = [10, 20, 30]
        self.assertEqual(S.shade(vals, 2, True), S._SHADES[-1])
        self.assertEqual(S.shade(vals, 0, True), S._SHADES[0])

    def test_direction_flips_for_a_measure_where_less_is_better(self):
        vals = [10, 20, 30]
        self.assertEqual(S.shade(vals, 0, False), S._SHADES[-1])
        self.assertEqual(S.shade(vals, 2, False), S._SHADES[0])

    def test_a_flat_row_is_not_shaded(self):
        self.assertEqual(S.shade([5, 5, 5], 1, True), "")

    def test_a_missing_week_is_not_shaded(self):
        self.assertEqual(S.shade([10, None, 30], 1, True), "")

    def test_a_missing_week_does_not_break_the_others(self):
        self.assertTrue(S.shade([10, None, 30], 2, True))


if __name__ == "__main__":
    unittest.main()


class Needle(unittest.TestCase):
    """text_errors writes a description, not a slice of the message."""

    def test_a_grammar_detail_keeps_only_the_words_in_the_text(self):
        self.assertEqual(S.needle_of("your looking (your → you're)"),
                         "your looking")

    def test_a_spelling_detail_keeps_the_misspelling(self):
        self.assertEqual(S.needle_of("intrested → interested"),
                         "intrested")

    def test_an_ascii_arrow_works_too(self):
        self.assertEqual(S.needle_of("biut -> but"), "biut")

    def test_a_plain_detail_is_left_alone(self):
        self.assertEqual(S.needle_of("i"), "i")

    def test_blank(self):
        self.assertEqual(S.needle_of(None), "")

    def test_the_needle_marks_the_real_message(self):
        got = S.mark("We don't have a exact 9am but we can do a 9:15",
                     S.needle_of("a exact (a → an)"))
        self.assertIn("<span class='bad'>a exact</span>", got)
