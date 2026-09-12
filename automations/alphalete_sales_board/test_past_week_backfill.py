"""A team's per-day average must DIVIDE IN THE SHEET, not freeze a number.

The bug (2026-09-11): `past_week_backfill` read each team's `Total Talk-To's`
and wrote `round(value / days, 1)`. That cell is a SUMIFS over the rep rows, so
its value depends on when you look — and the backfill runs BEFORE the rep rows
have their numbers. The SUMIFS returned 0, `float(cell or 0)` turned that into a
hard `0.0`, and six teams ended up reading "0.0 talk-to's per day" right next to
their own 939. The numbers arriving minutes later could not correct it: the cell
was a frozen value, not a formula.
"""
import unittest

from automations.alphalete_sales_board.past_week_backfill import team_avg_formula


class TeamAverageIsAFormula(unittest.TestCase):
    def setUp(self):
        # TK in column U (21), Total Talk-To's in W (23), the team row is 186
        self.f = team_avg_formula(23, 21, 186, 80)

    def test_it_is_a_formula(self):
        """The whole point: a value goes stale, a formula does not."""
        self.assertTrue(self.f.startswith("="))

    def test_it_divides_the_source_by_the_days(self):
        self.assertIn("W186/80", self.f)

    def test_a_week_with_no_knocks_leaves_the_row_clean(self):
        """The block's own rule: a team that never went out stays blank."""
        self.assertIn('IF(N(U186)=0,""', self.f)

    def test_nothing_countable_reads_as_a_dash_not_a_zero(self):
        """A '-' means nobody knows. A 0 claims they talked to nobody."""
        self.assertIn('NOT(ISNUMBER(W186))', self.f)
        self.assertIn('"-"', self.f)
        self.assertNotIn(',0)', self.f)

    def test_it_never_hardcodes_the_reading(self):
        """No digits other than the row and the day count."""
        import re
        nums = set(re.findall(r"\d+", self.f))
        self.assertEqual(nums, {"186", "80", "0"})   # row, days, the N()=0 test

    def test_days_change_with_the_team(self):
        self.assertIn("W186/24", team_avg_formula(23, 21, 186, 24))


if __name__ == "__main__":
    unittest.main()
