"""A renamed-in-place Tableau field must still match by name."""
import unittest

from automations.shared import tableau_columns as tc

HEADER_TODAY = [
    "Captain's Bonus Teams", "ICD Owner Name (rep)", "Rolling 4 Weeks",
    "New Internet ABP Mix % (Metrics)",
    "Jep New Internet Count (4 wk) (current)",      # renamed 2026-09-17
    "Past Due New Internet Count (4 wk) (copy)",
    "% of sales scheduled 6+ days out (4 wks)",
]


class TestColumnIndex(unittest.TestCase):
    def test_exact_still_wins(self):
        header = ["A", "Jep New Internet Count (4 wk)", "B"]
        self.assertEqual(tc.column_index(header, "Jep New Internet Count (4 wk)"), 1)

    def test_trailing_tag_is_ignored(self):
        self.assertEqual(
            tc.column_index(HEADER_TODAY, "Jep New Internet Count (4 wk)"), 4)

    def test_real_names_keep_their_parens(self):
        # '(4 wk)' / '(Metrics)' are part of the name, not editor tags.
        self.assertEqual(
            tc.column_index(HEADER_TODAY, "New Internet ABP Mix % (Metrics)"), 3)
        self.assertEqual(
            tc.column_index(HEADER_TODAY, "% of sales scheduled 6+ days out (4 wks)"), 6)

    def test_removed_column_still_reads_as_missing(self):
        self.assertIsNone(tc.column_index(HEADER_TODAY, "Tech Install % (Metrics)"))

    def test_ambiguous_is_refused(self):
        header = ["X (4 wk)", "X (4 wk) (copy)"]
        self.assertEqual(tc.column_index(header, "X (4 wk)"), 0)   # exact wins
        self.assertIsNone(tc.column_index(header, "X (4 wk) (new)"))  # 2 hits -> no guess

    def test_exact_match_beats_a_tagged_one(self):
        header = ["Jep New Internet Count (4 wk) (current)",
                  "Jep New Internet Count (4 wk)"]
        self.assertEqual(tc.column_index(header, "Jep New Internet Count (4 wk)"), 1)

    def test_stacked_tags(self):
        self.assertEqual(tc.base_name("X (copy) (2)"), "x")


class TestValueFor(unittest.TestCase):
    def test_tagged_key_is_found(self):
        values = {"jep new internet count (4 wk) (current)": "1,139"}
        self.assertEqual(
            tc.value_for(values, "Jep New Internet Count (4 wk)", str.lower), "1,139")

    def test_missing_returns_blank(self):
        self.assertEqual(tc.value_for({}, "anything", str.lower), "")


if __name__ == "__main__":
    unittest.main()
