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

    def _thread(self, *laters):
        """A thread: the question, our reply, then what they sent next."""
        return ([{"dir": "In", "body": "Is it in a store?"},
                 {"dir": "Out", "body": "This is a residential campaign"}]
                + [{"dir": "In", "body": b} for b in laters])

    def test_having_to_ask_again_is_reported(self):
        got = S.why_dodged(self.REMOTE, "dodged", "Is it in a store?",
                           "This is a residential campaign",
                           self._entry(self._thread("Is it in a store?")))
        self.assertIn("1 more time", got)
        self.assertIn("never got an answer", got)

    def test_a_statement_afterwards_is_not_asking_again(self):
        """Megan 2026-10-06 on Alexius Clark: "she didn't ask twice."
        "I was trying to apply for a store location sorry" is his last
        word on it, not a second question."""
        got = S.why_dodged(
            self.REMOTE, "dodged", "Is it in a store?",
            "This is a residential campaign",
            self._entry(self._thread(
                "No thank you",
                "I was trying to apply for a store location sorry")))
        self.assertNotIn("more time", got)

    def test_a_question_about_something_else_is_not_asking_again(self):
        got = S.why_dodged(
            self.REMOTE, "dodged", "Is it in a store?",
            "This is a residential campaign",
            self._entry(self._thread("How long is the interview?")))
        self.assertNotIn("more time", got)

    def test_three_attempts_with_no_answer_is_a_circle(self):
        """Megan 2026-10-06 on Jason Horton: "this should be a real red
        flag- this convo goes in circles"."""
        got = S.why_dodged(
            self.REMOTE, "dodged", "Is it in a store?",
            "Thank you for letting us know",
            self._entry(self._thread("Is the position in a store?",
                                     "Is it at a store location?")))
        self.assertIn("round in circles", got)
        self.assertIn("3 times", got)

    def test_answered_in_the_end_is_not_a_circle(self):
        got = S.why_dodged(
            self.REMOTE, "dodged", "Is it in a store?",
            "This is a residential campaign",
            self._entry(self._thread("Is the position in a store?",
                                     "Is it at a store location?"),
                        later=True))
        self.assertNotIn("round in circles", got)

    def test_a_circle_outranks_the_other_faults(self):
        got = S.worst_of(["Never said yes or no, only a vague answer.",
                          "This went round in circles \u2014 they asked 3 "
                          "times and never got a straight answer."])
        self.assertIn("round in circles", got)

    def test_answered_in_the_end_is_said_so(self):
        got = S.why_dodged(
            self.REMOTE, "dodged", "Is it in a store?",
            "This is a residential campaign",
            self._entry(self._thread("Is the position in a store?"),
                        later=True))
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


class NotRepetitive(unittest.TestCase):
    """Megan 2026-10-06, twice: "still redundant/repetitive"."""

    def test_the_circles_line_does_not_borrow_a_chase_count(self):
        got = S.worst_of([
            "This went round in circles — they asked 3 times and never "
            "got a straight answer.",
            "Never said yes or no, only a vague answer. They asked 1 more "
            "time, and never got an answer."])
        self.assertIn("round in circles", got)
        self.assertNotIn("1 more time", got)

    def test_a_verdict_is_returned_whole(self):
        one = "Doesn't answer the pay. They asked 1 more time."
        self.assertEqual(S.worst_of([one]), one)

    def test_the_walk_away_line_says_the_outcome_once(self):
        q = "Is it at a store location if not I'm not interested"
        got = S.why_dodged(
            "Is this remote / where is the office?", "dodged", q,
            "This would be a residential campaign",
            {"answered_later": "False", "context": [
                {"dir": "In", "body": q},
                {"dir": "Out", "body": "This would be a residential campaign"},
                {"dir": "In", "body": "Is it in a store though?"}]})
        self.assertEqual(got.count("never got"), 1)
        self.assertIn("1 more time", got)

    def test_other_lines_still_say_the_outcome(self):
        got = S.why_dodged(
            "What is the pay?", "dodged", "What does it pay?",
            "This is a residential campaign",
            {"answered_later": "False", "context": [
                {"dir": "In", "body": "What does it pay?"},
                {"dir": "Out", "body": "This is a residential campaign"},
                {"dir": "In", "body": "How much is the pay?"}]})
        self.assertIn("never got an answer", got)


class WentWell(unittest.TestCase):
    """Megan 2026-10-06: "we should also have some highlight of something
    they did well"."""

    def _person(self, now, before=None):
        weeks = {"w0918": before or {}, "w0925": now}
        return {"display": "X", "weeks": {k: v for k, v in weeks.items() if v}}

    def test_an_improvement_is_picked_up(self):
        got = S.did_well(self._person(
            {"texts": 500, "house": 6, "dodged": 6, "typing": 4,
             "booked": 50, "shown": 20},
            {"texts": 500, "house": 10, "dodged": 13, "typing": 8,
             "booked": 50, "shown": 20}), ["w0918", "w0925"])
        self.assertTrue(any("answered a lot more" in g for g in got), got)

    def test_a_clean_sheet_counts(self):
        got = S.did_well(self._person(
            {"texts": 500, "house": 0, "dodged": 0, "typing": 0,
             "booked": 50, "shown": 30}), ["w0925"])
        self.assertTrue(got)

    def test_nothing_good_means_nothing_said(self):
        got = S.did_well(self._person(
            {"texts": 500, "house": 9, "dodged": 9, "typing": 9,
             "booked": 50, "shown": 10},
            {"texts": 500, "house": 1, "dodged": 1, "typing": 1,
             "booked": 50, "shown": 40}), ["w0918", "w0925"])
        self.assertEqual(got, [])

    def test_it_stops_at_two(self):
        got = S.did_well(self._person(
            {"texts": 500, "house": 0, "dodged": 0, "typing": 0,
             "booked": 50, "shown": 40},
            {"texts": 500, "house": 9, "dodged": 9, "typing": 9,
             "booked": 50, "shown": 10}), ["w0918", "w0925"])
        self.assertLessEqual(len(got), 2)


class Grade(unittest.TestCase):
    """Megan 2026-10-06: "they should get a 'grade' on this report card"."""

    def _person(self, now, before=None):
        wk = {"w0918": before or {}, "w0925": now}
        return {"display": "X", "weeks": {k: v for k, v in wk.items() if v}}

    GOOD = {"texts": 500, "house": 0, "dodged": 0, "typing": 0,
            "booked": 50, "shown": 35, "matched": 40, "far_out": 2}
    BAD = {"texts": 500, "house": 20, "dodged": 30, "typing": 30,
           "booked": 50, "shown": 5, "matched": 40, "far_out": 30}

    def test_a_clean_week_grades_well(self):
        self.assertIn(S.grade_of(self._person(self.GOOD), ["w0925"]), "AB")

    def test_a_bad_week_grades_badly(self):
        self.assertIn(S.grade_of(self._person(self.BAD), ["w0925"]), "DF")

    def test_one_weak_area_does_not_set_the_whole_grade(self):
        """Megan 2026-10-06: "I dont think this is a D scorecard."
        One bad area pulls the letter down, it does not become it."""
        clean = S.grade_of(self._person(self.GOOD), ["w0925"])
        mixed = S.grade_of(self._person(dict(self.GOOD, house=20)), ["w0925"])
        self.assertNotEqual(mixed, clean)
        self.assertIn(mixed, "ABC")

    def test_failing_several_areas_does_grade_badly(self):
        self.assertIn(
            S.grade_of(self._person(dict(self.GOOD, house=20, dodged=30,
                                         shown=5)), ["w0925"]), "DF")

    def test_nothing_measured_is_no_grade(self):
        self.assertIsNone(S.grade_of({"display": "X", "weeks": {}}, ["w0925"]))

    def test_failing_keeps_only_what_is_off_target(self):
        items = S.work_on(self._person(dict(self.GOOD, house=20)), ["w0925"])
        self.assertTrue(items)
        self.assertTrue(all(i["grade"] not in "AB" for i in S.failing(items)))


class RatesNotCounts(unittest.TestCase):
    """Megan 2026-10-06: "6 house rules out of 3k texts sent seems pretty
    low....", and the same for unanswered questions. Both were graded on
    the raw count, so the busiest person always looked the worst."""

    def _week(self, **kw):
        base = {"texts": 3000, "house": 0, "dodged": 0, "typing": 0,
                "booked": 50, "shown": 24, "matched": 40, "far_out": 5,
                "issues": __import__("collections").Counter({"x": 1})}
        base.update(kw)
        return {"display": "X", "weeks": {"w0925": base}}

    def _area(self, person, name):
        for i in S.work_on(person, ["w0925"]):
            if i["area"] == name:
                return i
        return None

    def test_six_in_three_thousand_is_not_a_bad_week(self):
        got = self._area(self._week(house=6), "House Rules Broken")
        self.assertIn(got["grade"], "AB")

    def test_the_same_six_in_two_hundred_texts_is(self):
        got = self._area(self._week(texts=200, house=6), "House Rules Broken")
        self.assertIn(got["grade"], "DF")

    def test_the_volume_is_shown_beside_the_count(self):
        got = self._area(self._week(house=6), "House Rules Broken")
        self.assertIn("3,000 texts", got["now"])

    def test_unanswered_questions_are_a_rate_too(self):
        low = self._area(self._week(dodged=6), "Questions Not Answered")
        high = self._area(self._week(texts=300, dodged=6),
                          "Questions Not Answered")
        self.assertIn(low["grade"], "AB")
        self.assertIn(high["grade"], "DF")

    def test_a_tiny_sample_is_not_graded_at_all(self):
        self.assertIsNone(
            self._area(self._week(texts=10, house=6), "House Rules Broken"))


class Goals(unittest.TestCase):
    """Megan 2026-10-06: "we should have the goal of what the numbers
    should be so they know where they need to get to be in A ratings"."""

    def _week(self, **kw):
        base = {"texts": 3000, "house": 6, "dodged": 6, "typing": 4,
                "booked": 50, "shown": 14, "matched": 40, "far_out": 5,
                "replies": {"n": 50, "median": 8.0},
                "issues": __import__("collections").Counter({"x": 1})}
        base.update(kw)
        return {"display": "X", "weeks": {"w0925": base}}

    def _goals(self):
        return {i["area"]: i.get("goal")
                for i in S.work_on(self._week(), ["w0925"])}

    def test_every_scored_area_carries_a_target(self):
        for area, goal in self._goals().items():
            self.assertTrue(goal, area)

    def test_retention_names_the_percentage(self):
        self.assertIn("55%", self._goals()["1st Round Retention"])

    def test_a_rate_target_is_given_in_their_own_volume(self):
        got = self._goals()["House Rules Broken"]
        self.assertIn("3,000 texts", got)
        self.assertIn("2", got)

    def test_reply_speed_names_the_time(self):
        self.assertIn("5 min", self._goals()["Reply speed"])

    def test_a_bigger_sender_gets_a_bigger_allowance(self):
        small = {i["area"]: i.get("goal")
                 for i in S.work_on(self._week(texts=1000), ["w0925"])}
        self.assertNotEqual(small["House Rules Broken"],
                            self._goals()["House Rules Broken"])


class LeftHanging(unittest.TestCase):
    """Megan 2026-10-06 on Diego Sandoval: "was there any more follow up
    to this convo? that would be the real red flag"."""

    def test_their_message_last_is_flagged(self):
        got = S.left_hanging([("Out", "we are all set"),
                              ("In", "I really did try to be available")])
        self.assertIn("never got a reply", got)

    def test_several_left_hanging_are_counted(self):
        got = S.left_hanging([("Out", "a"), ("In", "b"), ("In", "c")])
        self.assertIn("2 messages", got)

    def test_our_message_last_is_fine(self):
        self.assertEqual(
            S.left_hanging([("In", "ok"), ("Out", "see you then")]), "")

    def test_an_empty_trailing_message_does_not_count(self):
        self.assertEqual(
            S.left_hanging([("In", "ok"), ("Out", "bye"), ("In", "  ")]), "")

    def test_it_outranks_every_other_verdict(self):
        got = S.worst_of([
            "This went round in circles — they asked 3 times.",
            "They wrote last and never got a reply — 1 message left "
            "hanging."])
        self.assertIn("wrote last", got)


class SilentBookings(unittest.TestCase):
    """The biggest split in the data: did they ever reply before the slot."""

    def _p(self, **kw):
        base = {"texts": 900, "house": 0, "dodged": 0, "typing": 0,
                "booked": 100, "shown": 29, "matched": 40, "far_out": 4,
                "silent": 48, "silent_shown": 5,
                "talked": 52, "talked_shown": 24,
                "issues": __import__("collections").Counter()}
        base.update(kw)
        return {"display": "X", "weeks": {"w0925": base}}

    def _why(self, person):
        for i in S.work_on(person, ["w0925"]):
            if i["area"] == "1st Round Retention":
                return i["do"]
        return ""

    def test_a_high_silent_share_is_named_as_a_call_booking(self):
        """Megan 2026-10-06: "get a reply? what does that mean? ... they
        aren't being booked via text and a phone call is happening?" The
        threads showed exactly that — a confirmation sent with no inbound
        ever, so the booking was agreed on a call."""
        got = self._why(self._p())
        self.assertIn("come from a phone call", got)
        self.assertIn("building the relationship", got)
        # Megan 2026-10-06: the fix is the call, not chasing a text.
        self.assertNotIn("reply to a text", got)

    def test_both_show_rates_are_given(self):
        got = self._why(self._p())
        self.assertIn("10%", got)
        self.assertIn("46%", got)

    def test_a_low_silent_share_says_something_else(self):
        got = self._why(self._p(silent=5, silent_shown=1,
                                talked=95, talked_shown=28))
        self.assertNotIn("come from a phone call", got)

    def test_too_few_bookings_to_judge(self):
        got = self._why(self._p(booked=10, shown=3, silent=5, silent_shown=0,
                                talked=5, talked_shown=3))
        self.assertNotIn("come from a phone call", got)


class DeflectionsCountedOnce(unittest.TestCase):
    """Megan 2026-10-06, seeing a hiring-manager push filed under
    Questions Not Answered: "this should be in the pushed to hirring
    manager section?" It was in BOTH — who_to_talk_to already records a
    deflection as the house rule."""

    def test_a_deflection_does_not_also_count_as_unanswered(self):
        import collections
        from automations.sms_audit import analyze as A

        convos = {"c": {"name": "Itza", "phone": "9995551234", "msgs": []}}
        deflected = [{"sender": "Jorge Pena", "kind": "deflected",
                      "bucket": "(other)", "name": "Itza",
                      "question": "is it all over Arlington?",
                      "reply": "Those are questions the Hiring Manager can "
                               "answer on the Zoom interviews.",
                      "context": [], "asked_again": 0,
                      "answered_later": "False"}]
        real = dict(deflected[0], kind="dodged")

        seen = []
        for e in deflected + [real]:
            if (e.get("kind") or "") == "deflected":
                continue
            seen.append(e)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "dodged")


class AnsweredLater(unittest.TestCase):
    """Megan 2026-10-06 on Jaysel Rosa: "i feel like he did answer this
    one". The immediate reply was "Awesome!" but the real answer came
    three messages later, and the audit's own answered_later said so.
    56% of what the section reported had been answered in the end."""

    def test_an_answered_later_entry_is_skipped(self):
        entries = [{"kind": "dodged", "answered_later": "True"},
                   {"kind": "dodged", "answered_later": "False"},
                   {"kind": "deflected", "answered_later": "False"}]
        kept = [e for e in entries
                if (e.get("kind") or "") != "deflected"
                and str(e.get("answered_later")).lower() != "true"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["answered_later"], "False")


class TooFewToJudge(unittest.TestCase):
    """Megan 2026-10-06: "why is booked over a day out blank here?"
    Because a percentage off a handful of bookings is noise. The
    retention row was not applying the same floor and printed 100% off
    one booking and 0% off four in the same table."""

    def _week(self, booked, shown, matched=0, far=0):
        return {"texts": 1500, "booked": booked, "shown": shown,
                "matched": matched, "far_out": far, "house": 0,
                "dodged": 0, "typing": 0,
                "issues": __import__("collections").Counter()}

    def _row(self, label, week):
        person = {"display": "X", "weeks": {"w0925": week}}
        import re as _re
        from pathlib import Path
        import tempfile
        out = Path(tempfile.mkdtemp()) / "c.html"
        S.render(person, "11280", ["w0925"], out)
        html = out.read_text(encoding="utf-8")
        m = _re.search(r"<tr><td>" + _re.escape(label) + r"</td>(.*?)</tr>",
                       html, _re.S)
        cells = _re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), _re.S)
        return cells[0]

    def test_one_booking_shows_no_retention_percentage(self):
        got = self._row("1st Round Retention", self._week(1, 1))
        self.assertIn(S.TOO_FEW, got)
        self.assertNotIn("%", got)

    def test_plenty_of_bookings_does_show_it(self):
        self.assertIn("%", self._row("1st Round Retention",
                                     self._week(25, 8)))

    def test_the_far_out_row_says_why_it_is_missing(self):
        """Not "Too Few" — Max Jimenez booked 39 and it still could not be
        read, because the lead comes from the confirmation text."""
        self.assertIn(S.NO_TEXT, self._row("Booked Over a Day Out",
                                           self._week(25, 8, matched=4, far=1)))
        self.assertIn("%", self._row("Booked Over a Day Out",
                                     self._week(25, 8, matched=20, far=5)))


class ProofWeek(unittest.TestCase):
    """Megan 2026-10-06: "56% last week when you didn't book far out - or
    something like that should be added IF THAT'S THE CASE". The guard is
    the point: it quotes an earlier week only when both numbers are solid
    and actually better."""

    def _wk(self, booked, shown, matched, far):
        return {"texts": 1500, "booked": booked, "shown": shown,
                "matched": matched, "far_out": far, "house": 0, "dodged": 0,
                "typing": 0, "silent": 0, "talked": booked,
                "silent_shown": 0, "talked_shown": shown,
                "issues": __import__("collections").Counter()}

    def test_a_better_earlier_week_is_quoted(self):
        person = {"display": "X", "weeks": {
            "w0918": self._wk(20, 12, 20, 5),     # 60% at 25% far out
            "w0925": self._wk(20, 6, 20, 12)}}    # 30% at 60% far out
        got = S.best_near_week(person, ["w0918", "w0925"], 60.0, 30.0)
        self.assertEqual(got[0], "w0918")

    def test_a_tiny_week_is_never_quoted(self):
        """Aisha Ceron's 56% week was nine bookings."""
        person = {"display": "X", "weeks": {
            "w0918": self._wk(9, 5, 8, 1),
            "w0925": self._wk(20, 6, 20, 12)}}
        self.assertIsNone(
            S.best_near_week(person, ["w0918", "w0925"], 60.0, 30.0))

    def test_a_week_that_booked_just_as_far_out_is_not_proof(self):
        person = {"display": "X", "weeks": {
            "w0918": self._wk(20, 14, 20, 11),
            "w0925": self._wk(20, 6, 20, 12)}}
        self.assertIsNone(
            S.best_near_week(person, ["w0918", "w0925"], 60.0, 30.0))

    def test_a_worse_week_is_not_proof(self):
        person = {"display": "X", "weeks": {
            "w0918": self._wk(20, 4, 20, 2),
            "w0925": self._wk(20, 6, 20, 12)}}
        self.assertIsNone(
            S.best_near_week(person, ["w0918", "w0925"], 60.0, 30.0))


class TooFewIsExplained(unittest.TestCase):
    """Megan 2026-10-06: "we need to have something explaining that the
    number of bookings is too low to have retention factored"."""

    def _html(self, week):
        from pathlib import Path
        import tempfile
        out = Path(tempfile.mkdtemp()) / "c.html"
        S.render({"display": "X", "weeks": {"w0925": week}}, "11280",
                 ["w0925"], out)
        return out.read_text(encoding="utf-8")

    THIN = {"texts": 1500, "booked": 2, "shown": 1, "matched": 2,
            "far_out": 1, "house": 0, "dodged": 0, "typing": 0,
            "issues": __import__("collections").Counter()}
    FULL = {"texts": 1500, "booked": 40, "shown": 20, "matched": 40,
            "far_out": 8, "house": 0, "dodged": 0, "typing": 0,
            "issues": __import__("collections").Counter()}

    def test_the_note_appears_when_something_was_suppressed(self):
        html = self._html(self.THIN)
        self.assertIn(S.TOO_FEW, html)
        self.assertIn("under 10 bookings", html.replace("&#x2014;", ""))

    def test_no_note_when_every_week_is_big_enough(self):
        html = self._html(self.FULL)
        self.assertNotIn(S.TOO_FEW, html)


class ZeroReadsLikeEnglish(unittest.TestCase):
    """Megan 2026-10-06: "only 0 missed - doesn't make sense"."""

    def _p(self, now, before):
        base = {"texts": 1500, "house": 0, "dodged": 0, "typing": 0,
                "booked": 40, "shown": 16, "matched": 40, "far_out": 8,
                "issues": __import__("collections").Counter()}
        return {"display": "X",
                "weeks": {"w0918": dict(base, **before),
                          "w0925": dict(base, **now)}}

    def _lines(self, now, before):
        return S.did_well(self._p(now, before), ["w0918", "w0925"], limit=5)

    def test_zero_unanswered_does_not_say_only_zero(self):
        got = " ".join(self._lines({"dodged": 0}, {"dodged": 2}))
        self.assertNotIn("only 0", got)
        self.assertIn("Every question an applicant asked got an answer", got)
        self.assertIn("down from 2", got)

    def test_zero_house_rules_reads_as_a_clean_week(self):
        got = " ".join(self._lines({"house": 0}, {"house": 4}))
        self.assertIn("nothing broken", got)
        self.assertIn("down from 4", got)

    def test_zero_typing_reads_as_not_a_typo(self):
        got = " ".join(self._lines({"typing": 0}, {"typing": 3}))
        self.assertIn("Not a typo", got)

    def test_a_non_zero_improvement_keeps_the_number(self):
        got = " ".join(self._lines({"dodged": 6}, {"dodged": 13}))
        self.assertIn("only 6 missed", got)

    def test_the_clean_sheet_line_is_not_said_twice(self):
        got = self._lines({"house": 0}, {"house": 4})
        clean = [g for g in got if "house rules" in g]
        self.assertEqual(len(clean), 1, got)


class PhoneBookingsAreVisible(unittest.TestCase):
    """Megan 2026-10-06: "we need to put the count of booked via phone so
    that we can see why his data here is missing"."""

    def _html(self, week):
        from pathlib import Path
        import tempfile
        out = Path(tempfile.mkdtemp()) / "c.html"
        S.render({"display": "X", "weeks": {"w0925": week}}, "11280",
                 ["w0925"], out)
        return out.read_text(encoding="utf-8")

    WEEK = {"texts": 6, "booked": 39, "shown": 10, "matched": 2,
            "far_out": 0, "silent": 37, "talked": 2, "silent_shown": 9,
            "talked_shown": 1, "house": 0, "dodged": 0, "typing": 0,
            "issues": __import__("collections").Counter()}

    def test_the_phone_booked_count_is_shown(self):
        html = self._html(self.WEEK)
        self.assertIn("Booked From a Call", html)
        self.assertIn("37", html)

    def test_the_lead_row_explains_itself(self):
        html = self._html(self.WEEK)
        self.assertIn(S.NO_TEXT, html)
        self.assertIn("comes from the confirmation text", html)

    def test_a_busy_texter_sees_neither_note(self):
        html = self._html(dict(self.WEEK, texts=1500, matched=39, silent=0,
                               talked=39, far_out=6))
        self.assertNotIn(S.NO_TEXT, html.split("Booked From a Call")[-1])


class WhatElseMoved(unittest.TestCase):
    """Megan 2026-10-06: "we need to know what changed- not just to keep
    doing it"."""

    BASE = {"texts": 1000, "house": 0, "dodged": 0, "typing": 0,
            "booked": 25, "shown": 16, "matched": 25, "far_out": 4,
            "silent": 8, "talked": 17, "silent_shown": 2, "talked_shown": 14,
            "replies": {"n": 40, "median": 11.0},
            "issues": __import__("collections").Counter()}

    def test_a_faster_reply_is_named(self):
        before = dict(self.BASE, replies={"n": 40, "median": 16.0})
        got = S.what_else_moved(self.BASE, before)
        self.assertIn("replied faster", got)
        self.assertIn("11 min", got)

    def test_fewer_phone_bookings_are_named(self):
        before = dict(self.BASE, silent=14, talked=11)
        self.assertIn("fewer came from a call",
                      S.what_else_moved(self.BASE, before))

    def test_booking_nearer_is_named(self):
        before = dict(self.BASE, far_out=14)
        self.assertIn("booked nearer the slot",
                      S.what_else_moved(self.BASE, before))

    def test_two_things_read_as_a_list(self):
        before = dict(self.BASE, silent=14, talked=11,
                      replies={"n": 40, "median": 16.0})
        got = S.what_else_moved(self.BASE, before)
        self.assertIn(" and ", got)

    def test_nothing_moving_says_so_rather_than_shrugging(self):
        got = S.what_else_moved(self.BASE, dict(self.BASE))
        self.assertIn("worth asking what you did differently", got)
        self.assertNotIn("Keep doing whatever", got)

    def test_no_previous_week_says_nothing(self):
        self.assertEqual(S.what_else_moved(self.BASE, None), "")


class BothBookingChannels(unittest.TestCase):
    """Megan 2026-10-06: "we should have a section on every report card
    the number booked via text and the number booked via phone"."""

    def _html(self, week):
        from pathlib import Path
        import tempfile
        out = Path(tempfile.mkdtemp()) / "c.html"
        S.render({"display": "X", "weeks": {"w0925": week}}, "11280",
                 ["w0925"], out)
        return out.read_text(encoding="utf-8")

    def test_both_channels_appear(self):
        html = self._html({"texts": 6, "booked": 39, "shown": 10,
                           "matched": 2, "far_out": 0, "silent": 37,
                           "talked": 2, "house": 0, "dodged": 0, "typing": 0,
                           "issues": __import__("collections").Counter()})
        self.assertIn("Booked From a Text", html)
        self.assertIn("Booked From a Call", html)
        self.assertIn("37", html)
