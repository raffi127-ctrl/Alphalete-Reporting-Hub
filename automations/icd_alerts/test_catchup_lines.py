"""A catch-up post to Slack carries the reps who sold while the machine was
offline -- never the standings block (Megan 2026-10-21, #takeoff-b2b)."""
import unittest

from automations.icd_alerts import post as P


class CatchupLines(unittest.TestCase):
    def test_att_board_keeps_only_moved_reps(self):
        sales = {"Sttefany Souza": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 5},
                 "Kalele Satele": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 1},
                 "Vicente Argueta": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}
        board = P.scoreboard_text(sales, ["Kalele Satele", "Vicente Argueta"],
                                  campaign="att")
        self.assertIn("TOTALS", board)
        out = P.catchup_lines(board)
        self.assertNotIn("TOTALS", out)
        self.assertNotIn("NL's", out)
        self.assertNotIn("INT:", out)
        self.assertNotIn("Sttefany", out)          # did not move
        self.assertEqual(2, len(out.splitlines()))
        self.assertIn("Kalele", out)
        self.assertIn("Vicente", out)

    def test_nds_and_box_boards_trim_the_same_way(self):
        nds = P.scoreboard_text({"A B": {"Air": 2, "NL": 1}}, ["A B"],
                                campaign="nds")
        self.assertIn("TOTALS", nds)
        self.assertEqual(1, len(P.catchup_lines(nds).splitlines()))
        self.assertNotIn("TOTALS", P.catchup_lines(nds))

    def test_empty_board_stays_empty(self):
        self.assertEqual("", P.catchup_lines(""))


if __name__ == "__main__":
    unittest.main()
