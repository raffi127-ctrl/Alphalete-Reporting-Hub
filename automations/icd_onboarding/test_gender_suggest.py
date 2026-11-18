"""The gender suggestion — and above all, what it refuses to suggest.

This value lands on a payroll record, so the tests that matter are the
NEGATIVE ones. Megan's own seven names from the week of 2026-11-18 are the
fixture: Ayodele, Marquette, Jovani, Penina, Sumera, Toni and Carmen. If any
of them ever starts returning an answer, that is the feature breaking, not
improving.

    python -m unittest automations.icd_onboarding.test_gender_suggest
"""
from __future__ import annotations

import unittest

from automations.icd_onboarding import board as B
from automations.icd_onboarding import gender_suggest as G

# Verbatim from Megan's note (2026-11-18).
MEGANS_SEVEN = ("Ayodele", "Marquette", "Jovani", "Penina", "Sumera", "Toni",
                "Carmen")


def _row(first, last="Smith", gender="", row=1):
    return {"Name": first, "Last Name": last, B.GENDER: gender, "_row": row}


class WhatItRefusesToGuess(unittest.TestCase):
    def test_megans_seven_are_all_blank(self):
        for name in MEGANS_SEVEN:
            self.assertEqual(G.suggest(name), "",
                             "%s must not be guessed" % name)

    def test_common_unisex_names_are_blank(self):
        for name in ("Jordan", "Taylor", "Casey", "Riley", "Alex", "Jamie",
                     "Morgan", "Quinn", "Avery", "Dana", "Jean", "Shannon",
                     "Tracy", "Kai", "Noor", "Ali"):
            self.assertEqual(G.suggest(name), "", "%s must be blank" % name)

    def test_a_name_it_has_never_seen_is_blank_not_a_coin_flip(self):
        # The default answer is "I don't know", not "probably male".
        for name in ("Zyphrenia", "Qwx", "Oluwaseun", "Thandiwe"):
            self.assertEqual(G.suggest(name), "")

    def test_nothing_at_all_is_blank(self):
        for name in ("", "   ", None, "123", "-", "!!"):
            self.assertEqual(G.suggest(name), "")

    def test_a_name_on_both_clear_lists_is_treated_as_ambiguous(self):
        # The invariant that stops a list edit deciding a payroll record.
        self.assertEqual(G.CLEAR_FEMALE & G.CLEAR_MALE, frozenset())
        for name in sorted(G._BOTH):
            self.assertEqual(G.suggest(name), "",
                             "%s is on both lists, so it must be blank" % name)

    def test_an_ambiguous_name_wins_over_a_clear_list(self):
        self.assertEqual((G.CLEAR_FEMALE | G.CLEAR_MALE) & G.AMBIGUOUS_ALL,
                         frozenset())

    def test_the_ambiguous_list_is_not_quietly_empty(self):
        # A guard with nothing in it would pass every other test here.
        self.assertGreater(len(G.AMBIGUOUS_ALL), 100)
        for name in MEGANS_SEVEN:
            self.assertIn(name.lower(), G.AMBIGUOUS_ALL)


class WhatItWillSuggest(unittest.TestCase):
    def test_clearly_one_way(self):
        self.assertEqual(G.suggest("Michael"), G.MALE)
        self.assertEqual(G.suggest("Stacy"), G.FEMALE)
        self.assertEqual(G.suggest("Rafael"), G.MALE)
        self.assertEqual(G.suggest("Megan"), G.FEMALE)

    def test_it_spells_them_the_way_apex_does(self):
        # An accepted suggestion is typed straight into Apex's dropdown.
        from automations.apex_new_starts import values as V
        for got in (G.MALE, G.FEMALE):
            self.assertEqual(V._gender(got), got)

    def test_accents_fold_so_jose_and_jose_are_one_person(self):
        self.assertEqual(G.suggest("José"), G.MALE)
        self.assertEqual(G.suggest("Jose"), G.MALE)

    def test_only_the_first_token_is_read(self):
        self.assertEqual(G.suggest("Mary-Jane"), G.FEMALE)
        self.assertEqual(G.suggest("Mary Jane"), G.FEMALE)
        self.assertEqual(G.suggest("  michael  "), G.MALE)

    def test_case_does_not_matter(self):
        self.assertEqual(G.suggest("MICHAEL"), G.MALE)


class ItNeverOverwrites(unittest.TestCase):
    def test_a_typed_answer_is_left_out_of_the_plan_entirely(self):
        # Not "written with the same value" -- left out. A re-run must not be
        # able to undo somebody's correction.
        rows = [_row("Michael", gender="Female")]
        self.assertEqual(G.plan(rows), [])
        self.assertEqual(G.wanted(rows), {})

    def test_even_an_odd_typed_value_is_respected(self):
        for typed in ("F", "male", "x", "prefer not to say"):
            self.assertEqual(G.plan([_row("Michael", gender=typed)]), [],
                             "%r was overwritten" % typed)

    def test_whitespace_only_counts_as_blank_and_is_filled(self):
        self.assertEqual(len(G.plan([_row("Michael", gender="  ")])), 1)

    def test_a_blank_clear_name_is_planned(self):
        got = G.plan([_row("Michael", "Anderson")])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "Michael Anderson")
        self.assertEqual(got[0]["suggest"], G.MALE)


class WhatStillNeedsAPerson(unittest.TestCase):
    def test_the_unclear_blanks_are_reported(self):
        rows = [_row(n, row=i) for i, n in enumerate(MEGANS_SEVEN, start=1)]
        self.assertEqual(G.plan(rows), [])
        still = G.unclear(rows)
        self.assertEqual(len(still), len(MEGANS_SEVEN))
        self.assertIn("nobody should guess", still[0]["why"])

    def test_an_already_answered_row_is_not_reported_as_outstanding(self):
        self.assertEqual(G.unclear([_row("Toni", gender="Female")]), [])

    def test_a_row_with_no_first_name_says_so_plainly(self):
        still = G.unclear([_row("")])
        self.assertEqual(len(still), 1)
        self.assertIn("no first name", still[0]["why"])

    def test_plan_and_unclear_together_cover_every_blank(self):
        rows = [_row("Michael", row=1), _row("Toni", row=2),
                _row("Stacy", row=3, gender="Female"), _row("", row=4)]
        blanks = [r for r in rows if not str(r[B.GENDER]).strip()]
        self.assertEqual(len(G.plan(rows)) + len(G.unclear(rows)),
                         len(blanks))


class TheTint(unittest.TestCase):
    def test_a_suggestion_is_not_tinted_the_done_colour(self):
        # Green means a step is finished; a guess nobody has checked is not.
        self.assertNotEqual(B.SUGGESTED, B.GREEN)

    def test_gender_is_still_a_column_a_person_owns(self):
        self.assertIn(B.GENDER, B.BY_HAND)


if __name__ == "__main__":
    unittest.main()


class ThePreviewCountsWhatItWouldDo(unittest.TestCase):
    """A dry run reports the cells it WOULD fill, not 0.

    Found on the first live preview against Raf's board: it listed eleven
    suggestions and then said "0 cell(s) would be filled", which reads as
    "this does nothing" to the one person whose opinion decides whether the
    feature stays on.
    """

    def test_dry_run_returns_the_planned_count(self):
        import datetime as dt

        from automations.icd_onboarding import gender_suggest as GS

        rows = [_row("Michael", "Anderson", row=1),
                _row("Stacy", "Perez", row=2),
                _row("Toni", "Lopez", row=3)]          # not guessable

        class _WS:
            def get_all_values(self):
                return [["Week of", "Name", "Last Name", B.GENDER]]

        monday = B.week_start_of(dt.date.today())
        saved = (GS.B.for_week, )
        try:
            # Stand in for the sheet: the point is the RETURN VALUE, so the
            # board read is replaced rather than mocked in depth.
            GS.B.for_week = staticmethod(lambda _rows, _wk: rows)
            import automations.icd_onboarding.sheet as S
            import automations.icd_onboarding.fillers as F
            old = (S.open_board, S.layout, S.rows_of, F.workbook_for)
            try:
                S.open_board = staticmethod(lambda *_a, **_k: _WS())
                S.layout = staticmethod(lambda _g: {B.GENDER: 3})
                S.rows_of = staticmethod(lambda _g: rows)
                F.workbook_for = staticmethod(lambda _k: object())
                n = GS.fill("raf", monday, dry_run=True, log=lambda *_a: None)
            finally:
                (S.open_board, S.layout, S.rows_of, F.workbook_for) = old
        finally:
            GS.B.for_week = saved[0]
        self.assertEqual(n, 2)      # Michael and Stacy; Toni is left alone
