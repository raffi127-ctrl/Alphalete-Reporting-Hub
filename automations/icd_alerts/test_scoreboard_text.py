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

    def test_a_box_office_gets_contracts_and_kwh_no_big_huge(self):
        """Megan 2026-09-22: "we should remove the big/huge verbiage"."""
        sales = {"COLTEN STILES": {"Sales": 2, "Volume": 27000, "Big": 2, "Huge": 1},
                 "VIANEY SILVA": {"Sales": 1, "Volume": 165000, "Big": 1, "Huge": 1},
                 "KYLE STALLARD": {"Sales": 1, "Volume": 9500, "Big": 0, "Huge": 0},
                 "NOBODY YET": {"Sales": 0, "Volume": 0, "Big": 0, "Huge": 0}}
        out = P.scoreboard_text(sales, ["COLTEN STILES"], campaign="b2b_box")
        lines = out.split("\n")
        self.assertEqual(lines[0], "Colten Stiles 2 (27,000 kWh) \U0001F525")
        self.assertEqual(lines[1], "Vianey Silva 1 (165,000 kWh)")
        self.assertEqual(lines[2], "Kyle Stallard 1 (9,500 kWh)")
        self.assertNotIn("Nobody Yet", out)
        self.assertEqual(lines[3], "")
        self.assertEqual(lines[4], "Contracts: 4")
        self.assertEqual(lines[5], "kWh: 201,500")
        self.assertEqual(lines[6], "\U0001F3C6 TOTALS: 4")
        for word in ("Big", "Huge"):
            self.assertNotIn(word, out)

    def test_nds_shows_only_lines_and_air(self):
        """Colten 2026-09-22: NDS sells Air + lines, no DTV, no internet."""
        sales = {"HERMIONE HICKS": M(0, 1, 0, 5), "SEBASTIAN GRIMALDO": M(0, 0, 0, 5),
                 "NOBODY": M()}
        out = P.scoreboard_text(sales, ["HERMIONE HICKS"], campaign="nds")
        lines = out.split("\n")
        self.assertEqual(lines[0], "Hermione Hicks 6 (1 Air/Up, 5 NL) \U0001F525")
        self.assertEqual(lines[1], "Sebastian Grimaldo 5 (5 NL)")
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "Air/Upgrades: 1")
        self.assertEqual(lines[4], "NL's: 10")
        self.assertEqual(lines[5], "\U0001F3C6 TOTALS: 11")
        for word in ("INT:", "DTV", " Up,", " Up)"):
            self.assertNotIn(word, out)

    def test_att_keeps_the_full_block(self):
        out = P.scoreboard_text({"A": M(1, 1, 1, 1)}, [], campaign="att")
        for word in ("INT: 1", "Upgrades: 1", "DTV: 1", "NL's: 1", "TOTALS: 4"):
            self.assertIn(word, out)

    def test_a_box_office_with_no_contracts_sends_nothing(self):
        out = P.scoreboard_text({"A": {"Sales": 0, "Volume": 0}}, [], campaign="b2b_box")
        self.assertEqual(out, "")

    def test_an_unknown_shape_gets_none(self):
        out = P.scoreboard_text({"A": {"Int": 1}}, ["A"], campaign="energywell") if False else ""
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
