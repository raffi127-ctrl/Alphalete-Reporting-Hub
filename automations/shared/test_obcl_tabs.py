"""One tab-title parser for the D2D OBCL family.

Every case here was a real difference between the four parsers this replaced
(measured 2026-09-26), so each test names which module used to get it wrong.
"""
import datetime as dt
import unittest

from automations.shared import obcl_tabs as T

SEP = dt.date(2026, 9, 26)
DEC = dt.date(2026, 12, 21)
JAN = dt.date(2027, 1, 11)


class ParsesTheTitle(unittest.TestCase):
    def test_the_ordinary_case(self):
        self.assertEqual(T.tab_date("D2D OBCL 9.28", SEP), dt.date(2026, 9, 28))

    def test_a_slash_separator(self):
        """new_start_followup and apex accepted '.' only, so "9/28" was
        invisible to both."""
        self.assertEqual(T.tab_date("D2D OBCL 9/28", SEP), dt.date(2026, 9, 28))

    def test_an_explicit_two_digit_year(self):
        """new_start_followup read '9.28.26' as month 28 / day 26."""
        self.assertEqual(T.tab_date("D2D OBCL 9.28.26", SEP),
                         dt.date(2026, 9, 28))

    def test_an_explicit_four_digit_year(self):
        self.assertEqual(T.tab_date("D2D OBCL 9.28.2026", SEP),
                         dt.date(2026, 9, 28))

    def test_case_and_spacing_do_not_matter(self):
        for t in ("d2d obcl 9.28", "  D2D   OBCL   9.28  ", "D2D OBCL  9.28"):
            self.assertEqual(T.tab_date(t, SEP), dt.date(2026, 9, 28), t)


class InfersTheYearBothWays(unittest.TestCase):
    def test_january_read_in_december_is_next_year(self):
        """THE headshots BUG: its inference only ever subtracted a year, so the
        January tab built in late December came back as January of the year just
        gone — which sorts OLDEST, and find_week_tab takes the newest."""
        self.assertEqual(T.tab_date("D2D OBCL 1.4", DEC), dt.date(2027, 1, 4))

    def test_december_read_in_january_is_last_year(self):
        self.assertEqual(T.tab_date("D2D OBCL 12.28", JAN), dt.date(2026, 12, 28))

    def test_an_explicit_year_is_never_second_guessed(self):
        self.assertEqual(T.tab_date("D2D OBCL 1.4.26", DEC), dt.date(2026, 1, 4))


class RefusesRatherThanGuesses(unittest.TestCase):
    def test_the_rolling_tab_has_no_date(self):
        self.assertIsNone(T.tab_date("D2D OBCL", SEP))
        self.assertTrue(T.is_rolling("D2D OBCL"))
        self.assertFalse(T.is_rolling("D2D OBCL 9.28"))

    def test_anything_between_the_prefix_and_the_date_is_refused(self):
        """Strict on purpose: missing a tab is loud, picking the WRONG tab is
        silent and writes over good rows. Two of the four used to accept this."""
        self.assertIsNone(T.tab_date("D2D OBCL WEEK 9.28", SEP))

    def test_an_impossible_date_is_not_a_week(self):
        for bad in ("D2D OBCL 2.30", "D2D OBCL 13.1", "D2D OBCL 0.0"):
            self.assertIsNone(T.tab_date(bad, SEP), bad)

    def test_another_workbooks_tabs_are_not_ours(self):
        for other in ("Sales Board WE 9.27", "Line Up WE 9.28", "Recruiting",
                      "", "   "):
            self.assertIsNone(T.tab_date(other, SEP), other)


TITLES = ["D2D OBCL", "D2D OBCL 9.14", "D2D OBCL 9.28", "D2D OBCL 9.21",
          "Recruiting"]


class EachCallerKeepsItsOwnPolicy(unittest.TestCase):
    def test_newest_is_newest_outright_not_newest_in_the_past(self):
        """The team rolls one tab forward: on 2026-08-30 the only dated tab was
        8.31, next week's. An 'on or before today' rule would skip it."""
        d, title = T.newest(TITLES, SEP)
        self.assertEqual((d, title), (dt.date(2026, 9, 28), "D2D OBCL 9.28"))

    def test_dated_is_newest_first_and_drops_the_rolling_tab(self):
        self.assertEqual([t for _, t in T.dated(TITLES, SEP)],
                         ["D2D OBCL 9.28", "D2D OBCL 9.21", "D2D OBCL 9.14"])

    def test_for_week_is_exact_never_a_near_miss(self):
        self.assertEqual(T.for_week(TITLES, dt.date(2026, 9, 21)),
                         "D2D OBCL 9.21")
        # One day off is not this week. The follow-up report turns None into a
        # refusal rather than texting last week's leaders.
        self.assertIsNone(T.for_week(TITLES, dt.date(2026, 9, 22)))

    def test_in_week_takes_the_earliest_inside_the_window(self):
        self.assertEqual(T.in_week(TITLES, dt.date(2026, 9, 21)),
                         "D2D OBCL 9.21")
        self.assertEqual(T.in_week(TITLES, dt.date(2026, 9, 15)),
                         "D2D OBCL 9.21")
        self.assertIsNone(T.in_week(TITLES, dt.date(2026, 10, 5)))

    def test_nothing_dated_means_nothing_found(self):
        self.assertIsNone(T.newest(["D2D OBCL", "Recruiting"], SEP))
        self.assertIsNone(T.for_week(["D2D OBCL"], dt.date(2026, 9, 28)))


if __name__ == "__main__":
    unittest.main()
