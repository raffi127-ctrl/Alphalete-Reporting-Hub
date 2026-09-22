"""ECO offices get the day's standings texted to their group, in Raf's
partner-chat layout (Megan, 2026-09-22)."""
import unittest

from automations.icd_alerts import post as P


def M(i=0, u=0, d=0, n=0):
    return {"Int": i, "Int Up": u, "DTV": d, "NL": n}


class ScoreboardTextTest(unittest.TestCase):
    SALES = {"ZORIA JOHNSON": M(1, 0, 0, 4), "CHLOE JOHNSON": M(3),
             "JUSTIN AVILA": M(2, 1), "NOBODY YET": M()}

    def test_rafs_layout_highest_first_with_totals(self):
        out = P.scoreboard_text(self.SALES, ["CHLOE JOHNSON"])
        lines = out.split("\n")
        self.assertEqual(lines[0], "Zoria Johnson 5 (1 Int, 4 NL)")
        self.assertEqual(lines[1], "Chloe Johnson 3 (3 Int) " + "\U0001F525")
        self.assertEqual(lines[2], "Justin Avila 3 (2 Int, 1 Up)")
        self.assertNotIn("Nobody Yet", out, "a rep with no sale has no line")
        self.assertIn("INT: 6", out)
        self.assertIn("Upgrades: 1", out)
        self.assertIn("DTV: 0", out)
        self.assertIn("NL's: 4", out)
        self.assertIn("TOTALS: 11", out)

    def test_baseline_has_no_flames(self):
        out = P.scoreboard_text(self.SALES, [])
        self.assertNotIn("\U0001F525", out)

    def test_no_team_or_weekly_lines_yet(self):
        out = P.scoreboard_text(self.SALES, [])
        self.assertNotIn("Week", out)
        self.assertNotIn("Unassigned", out)

    def test_name_fixes_apply(self):
        out = P.scoreboard_text({"J DOE": M(1)}, ["J DOE"],
                                show=lambda r: "Jane Doe")
        self.assertTrue(out.startswith("Jane Doe 1 (1 Int) \U0001F525"), out)

    def test_nobody_sold_means_no_text(self):
        self.assertEqual(P.scoreboard_text({"A": M(), "B": M()}, []), "")

    def test_a_box_office_gets_none(self):
        """Box relays Sales/Volume; this layout would read every rep as 0."""
        out = P.scoreboard_text({"A": {"Sales": 2, "Volume": 27000}}, ["A"],
                                campaign="b2b_box")
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
