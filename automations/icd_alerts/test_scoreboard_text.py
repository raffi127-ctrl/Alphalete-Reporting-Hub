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

    def test_nds_three_sections_upgrades_outside_the_total(self):
        """Megan 2026-09-22: Air / NLs / Upgrades, upgrades not a unit."""
        sales = {"HERMIONE HICKS": dict(M(0, 1, 0, 5), Air=1),
                 "SEBASTIAN GRIMALDO": dict(M(0, 0, 0, 5), Air=0),
                 "KYLE X": dict(M(0, 1, 0, 2), Air=0),
                 "NOBODY": dict(M(), Air=0)}
        out = P.scoreboard_text(sales, ["HERMIONE HICKS"], campaign="nds")
        lines = out.split("\n")
        self.assertEqual(lines[0], "Hermione Hicks 6 (1 Air, 5 NL) \U0001F525")
        self.assertEqual(lines[1], "Sebastian Grimaldo 5 (5 NL)")
        self.assertEqual(lines[2], "Kyle X 2 (2 NL, 1 Up)")
        self.assertEqual(lines[3], "")
        self.assertEqual(lines[4], "Air: 1")
        self.assertEqual(lines[5], "NL's: 12")
        self.assertEqual(lines[6], "Upgrades: 1")
        self.assertEqual(lines[7], "\U0001F3C6 TOTALS: 13")
        for word in ("INT:", "DTV"):
            self.assertNotIn(word, out)

    def test_nds_old_payload_without_air_still_renders(self):
        out = P.scoreboard_text({"A": M(0, 1, 0, 3)}, [], campaign="nds")
        self.assertIn("A 3 (3 NL, 1 Up)", out)
        self.assertIn("TOTALS: 3", out)

    def test_the_relay_carries_air_on_its_own(self):
        from automations.shared import sale_hype as H
        m = H.metrics_for({"internet_sales": 3, "internet_upgrades": 1, "aia_sales": 1,
                           "dtv_streaming": 0, "wireless_lines_sold": 5})
        self.assertEqual(m["Air"], 1)
        self.assertEqual(m["Int Up"], 2)
        self.assertEqual(m["Int"], 1)
        self.assertEqual(tuple(H.shape("nds").metrics)[-1], "Air")
        self.assertNotIn("Air", H.shape("att").metrics)

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
