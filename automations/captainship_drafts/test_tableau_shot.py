"""§2 for captains whose Tableau team value is gone (Carlos, Atef — 2026-10-14)."""
import unittest
from unittest import mock

from automations.captainship_drafts import tableau_shot as t


class OwnerFilterValues(unittest.TestCase):
    def test_keeps_case_only_variants(self):
        # Tableau's URL filter is case-sensitive: 'Jackie Leroy' misses 'Jackie LeRoy'.
        out = t._owner_filter_values(["Jackie Leroy"],
                                     {"Jackie LeRoy": ["Jackie Leroy"]})
        self.assertEqual(out, ["Jackie Leroy", "Jackie LeRoy"])

    def test_board_spelling_pulls_in_tableau_spelling(self):
        out = t._owner_filter_values(["Dhey Patel", "Sabrina Alicea"],
                                     {"Dhyey Patel": ["Dhey Patel"]})
        self.assertEqual(out, ["Dhey Patel", "Dhyey Patel", "Sabrina Alicea"])


class BoardRosterUrl(unittest.TestCase):
    def test_every_team_and_the_board_owners(self):
        with mock.patch("automations.carlos_captainship_headcount.roster."
                        "board_roster", return_value=["Atef Choudhury"]), \
             mock.patch("automations.focus_office_att.aliases.load_aliases",
                        return_value={}):
            url = t._board_roster_url(t._B2B_VIEW, "Atef")
        self.assertIn("Unassigned", url)
        self.assertIn("Owner%20Name=Atef%20Choudhury", url)
        self.assertNotIn("Atef%27s%20Team", url)

    def test_spec_for_does_not_read_the_board(self):
        # email_build calls _spec_for just to ask "configured?" — no Sheets read.
        with mock.patch("automations.carlos_captainship_headcount.roster."
                        "board_roster", side_effect=AssertionError):
            self.assertIsNotNone(t._spec_for("carlos", "b2b"))


if __name__ == "__main__":
    unittest.main()
