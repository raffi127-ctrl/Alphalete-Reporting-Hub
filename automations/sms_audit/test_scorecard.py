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


class WhyDodged(unittest.TestCase):
    """Megan 2026-10-06: say why it is wrong, in red."""

    REMOTE = "Is this remote / where is the office?"

    def test_a_known_bucket_names_the_topic(self):
        got = S.why_dodged(self.REMOTE)
        self.assertIn("whether the job is remote and where the office is", got)

    def test_four_dodges_do_not_get_one_sentence(self):
        """Megan 2026-10-06: "this isn't all the same..." — they were not."""
        pairs = [
            ("Does the position require employees to drive to different job "
             "sites, or is the work based out of the Irving office?",
             "This is a residential campaign"),
            ("Is this in a store?", "A quick 15-20 minutes"),
            ("Is the position in a store?", "This is a residential campaign"),
        ]
        said = [S.why_dodged(self.REMOTE, "dodged", q, r) for q, r in pairs]
        # Not one sentence for all of them. Two of the three ARE the same
        # fault — a yes-or-no question answered with neither — and saying
        # so twice is right; the third is a reply about something else.
        self.assertGreater(len(set(said)), 1)
        self.assertIn("how long the interview is", said[1])

    def test_a_reply_about_the_interview_length_is_named_as_that(self):
        got = S.why_dodged(self.REMOTE, "dodged", "Is this in a store?",
                           "A quick 15-20 minutes")
        self.assertIn("how long the interview is", got)

    def test_a_vague_answer_is_named_as_vague_not_as_missing(self):
        """Megan 2026-10-06: "technically this does answer but is a bit
        dodgy, should ask something back"."""
        got = S.why_dodged(self.REMOTE, "dodged", "Is the position in a store?",
                           "This is a residential campaign")
        self.assertIn("vague", got)
        self.assertNotIn("Doesn't answer", got)
        # The how-to-fix lives on the section, not on every quote.
        self.assertIn("ask", S.recovery_for(self.REMOTE).lower())

    def test_a_long_question_that_really_was_not_answered(self):
        """Lizbeth Gonzalez's: not a bare yes/no, and genuinely unanswered."""
        got = S.why_dodged(
            self.REMOTE, "dodged",
            "I had one quick question regarding the role. Does the position "
            "require employees to drive to different job sites?",
            "This is a residential campaign")
        self.assertIn("Doesn't answer", got)

    def test_the_red_line_states_the_fault_and_does_not_coach(self):
        """Megan 2026-10-06: "that's a weird way to coach that" — the
        coaching belongs in the green Instead: box, not the red line."""
        got = S.why_dodged(self.REMOTE, "dodged",
                           "I had a question about the role. Where is it?",
                           "This is a residential campaign")
        self.assertNotIn("asked back", got)
        self.assertNotIn("Say ", got)

    def test_a_straight_no_is_not_called_vague(self):
        got = S.why_dodged(self.REMOTE, "dodged", "Is the position in a store?",
                           "No, it is not in a store")
        self.assertNotIn("vague", got)

    def test_a_reply_giving_a_time_when_none_was_asked_for(self):
        got = S.why_dodged(self.REMOTE, "dodged", "Is this in a store?",
                           "Tomorrow at 9:15")
        self.assertIn("Gave a time", got)

    def test_a_duration_reply_to_a_duration_question_is_not_a_wrong_topic(self):
        got = S.why_dodged("How long is the interview / what's next?",
                           "dodged", "How long is it?", "About 20 minutes")
        self.assertNotIn("Gave how long", got)

    def test_a_deflection_reads_differently_from_a_dodge(self):
        got = S.why_dodged("What is the pay?", "deflected")
        self.assertIn("someone else", got)
        self.assertNotIn("isn't relevant", got)

    def test_shorthand_has_its_own_line(self):
        self.assertIn("shorthand", S.why_dodged("What is the pay?", "informal"))

    def test_an_unknown_bucket_still_reads_as_english(self):
        got = S.why_dodged("Something We Have Not Seen?")
        self.assertIn("something we have not seen", got)
        self.assertNotIn("?.", got)

    def test_no_bucket_at_all(self):
        self.assertIn("the question", S.why_dodged(None))


class DodgeContext(unittest.TestCase):
    """The reason reads the surrounding messages, not just the pair."""

    REMOTE = "Is this remote / where is the office?"

    def _entry(self, ctx, again=0, later=False):
        return {"context": ctx, "asked_again": again,
                "answered_later": str(later)}

    def test_several_questions_in_a_row_are_named_as_that(self):
        ctx = [{"dir": "In", "body": "Is this in a store?"},
               {"dir": "In", "body": "How long is the interview?"},
               {"dir": "Out", "body": "A quick 15-20 minutes"}]
        got = S.why_dodged(self.REMOTE, "dodged", "Is this in a store?",
                           "A quick 15-20 minutes", self._entry(ctx))
        self.assertIn("2 things in a row", got)

    def test_it_does_not_claim_the_reply_answered_one_of_them(self):
        """"Thank you for letting us know" answers none of them."""
        ctx = [{"dir": "In", "body": "Can you verify?"},
               {"dir": "In", "body": "I have not applied"},
               {"dir": "Out", "body": "Thank you for letting us know"}]
        got = S.why_dodged("Which role / which company is this?", "dodged",
                           "Can you verify?", "Thank you for letting us know",
                           self._entry(ctx))
        self.assertNotIn("answers the other", got)

    def test_a_single_question_is_not_called_a_pile_up(self):
        ctx = [{"dir": "In", "body": "Is this in a store?"},
               {"dir": "Out", "body": "This is a residential campaign"}]
        got = S.why_dodged(self.REMOTE, "dodged", "Is this in a store?",
                           "This is a residential campaign", self._entry(ctx))
        self.assertNotIn("in a row", got)

    def test_having_to_ask_again_is_reported(self):
        got = S.why_dodged(self.REMOTE, "dodged", "Is it in a store?",
                           "This is a residential campaign",
                           self._entry([], again=1))
        self.assertIn("1 more time", got)
        self.assertIn("never got an answer", got)

    def test_three_attempts_with_no_answer_is_a_circle(self):
        """Megan 2026-10-06 on Jason Horton: "this should be a real red
        flag- this convo goes in circles"."""
        got = S.why_dodged(self.REMOTE, "dodged", "Is it in a store?",
                           "Thank you for letting us know",
                           self._entry([], again=2))
        self.assertIn("round in circles", got)
        self.assertIn("3 times", got)

    def test_answered_in_the_end_is_not_a_circle(self):
        got = S.why_dodged(self.REMOTE, "dodged", "Is it in a store?",
                           "This is a residential campaign",
                           self._entry([], again=2, later=True))
        self.assertNotIn("round in circles", got)

    def test_a_circle_outranks_the_other_faults(self):
        got = S.worst_of(["Never said yes or no, only a vague answer.",
                          "This went round in circles \u2014 they asked 3 "
                          "times and never got a straight answer."])
        self.assertIn("round in circles", got)

    def test_answered_in_the_end_is_said_so(self):
        got = S.why_dodged(self.REMOTE, "dodged", "Is it in a store?",
                           "This is a residential campaign",
                           self._entry([], again=1, later=True))
        self.assertIn("1 more time", got)
        self.assertNotIn("never got an answer", got)


class WeakAnswers(unittest.TestCase):
    def test_a_vague_yes_no_reply_is_weak(self):
        self.assertTrue(S.is_weak("Is the position in a store?",
                                  "This is a residential campaign"))

    def test_a_plain_answer_is_not_weak(self):
        self.assertFalse(S.is_weak("Is the position in a store?",
                                   "No, it is door to door."))

    def test_a_reply_that_asks_back_is_not_weak(self):
        self.assertFalse(S.is_weak("Is the position in a store?",
                                   "It is residential. Does that work?"))

    def test_every_bucket_has_real_advice(self):
        for bucket in S.TOPICS:
            advice = S.recovery_for(bucket)
            self.assertGreater(len(advice), 30, bucket)
            self.assertTrue(advice.endswith("."), bucket)

    def test_the_which_role_advice_is_megans(self):
        got = S.recovery_for("Which role / which company is this?")
        self.assertIn("sounds familiar", got)
        # Megan 2026-10-06: "employement - not work".
        self.assertIn("still looking for employment", got)

    def test_a_walk_away_warning_reads_differently(self):
        """Megan 2026-10-06: "these can't be the same"."""
        plain = S.why_dodged("Is this remote / where is the office?",
                             "dodged", "Is the position in a store?",
                             "This is a residential campaign")
        walks = S.why_dodged("Is this remote / where is the office?",
                             "dodged",
                             "Is it at a store location if not I'm not "
                             "interested",
                             "This would be a residential campaign")
        self.assertNotEqual(plain, walks)
        self.assertIn("walk away", walks)
        self.assertNotIn("walk away", plain)

    def test_an_unknown_bucket_still_gets_advice(self):
        self.assertTrue(S.recovery_for("Something new?"))
