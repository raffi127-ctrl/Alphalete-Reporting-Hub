"""Carlos's sales text carries team totals off the Vantura NDS Sales Board
(2026-11-19: "raf has team sales ... can we get the same thing")."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import post as P
from automations.icd_alerts import vantura_teams as VT


def _grid():
    hdr = ["#", "REP", "Current Week", "Last Wk", "Monday", "Tuesday", "Wednesday",
           "Thursday", "Friday", "Saturday", "Sunday", "Campaign", "Trainer",
           "Field Status", "Team", "Leadership Status", "Secondary Status"]

    def rep(i, name, team):
        return [str(i), name, "0", "0"] + [""] * 7 + ["NDS", "", "", team, "Level 1", ""]
    g = [[""], ["WE", "11.22"], [""], hdr,
         rep(1, "Stefany Zaldivar", "Diego"),
         rep(2, "Nick Smedra", "Direct Hit"),
         rep(3, "Nathaly Benitez", "Cinthya"),
         rep(4, "Carlos Hidalgo", "Akatsuki"),
         rep(5, "No Team Yet", ""),
         ["", "AT&T NDS", "50", "133"] + [""] * 7 + ["NDS"],
         [""],
         ["", "Teams — Current Week", "Apps", "Total Head Count"],
         ["", "AT&T NDS", "47", "19"],
         ["", "Cinthya", "14", "5"],
         ["", "Direct Hit", "10", "4"],
         ["", "Diego", "9", "3"],
         ["", "Unaccounted For", "0", "0"]]
    return g


class Book(unittest.TestCase):
    def test_teams_come_from_the_boards_own_box_and_names_match_like_the_fill(self):
        book = VT.from_grid(_grid(), "NDS Sales Board")
        self.assertEqual(book.teams, ["Cinthya", "Direct Hit", "Diego"])
        self.assertEqual(book.team_for("STEFANY MICHELLE ZALDIVAR JUSTINIANO"), "Diego")
        self.assertEqual(book.team_for("Nicholas Paul Smedra"), "Direct Hit")
        self.assertEqual(book.team_for("Nathaly Elizabeth Molina Benitez"), "Cinthya")
        self.assertEqual(book.team_for("No Team Yet"), "")
        self.assertEqual(book.team_for("Somebody Else"), "")

    def test_no_box_falls_back_to_the_team_column(self):
        g = [r for r in _grid() if "Teams" not in " ".join(r)]
        self.assertEqual(VT.box_teams(g), [])
        self.assertEqual(VT.from_grid(g).teams, ["Akatsuki", "Cinthya", "Diego", "Direct Hit"])

    def test_the_nds_text_gets_one_line_per_team_that_adds_up_to_totals(self):
        book = VT.from_grid(_grid(), "NDS Sales Board")
        sales = {"NATHALY BENITEZ": {"NL": 4},
                 "NICHOLAS SMEDRA": {"NL": 1, "Int Up": 2, "Air": 1},
                 "NEW GUY": {"NL": 1}}
        text = P.scoreboard_text(sales, [], "nds", None, teams=book)
        tail = text.split("TOTALS: 7")[1].strip().splitlines()
        self.assertEqual(tail, ["Cinthya: 4 \U0001F947", "Direct Hit: 2", "Diego: 0",
                                "Unassigned: 1"])
        # no book, no block -- every other NDS office reads as before
        self.assertTrue(P.scoreboard_text(sales, [], "nds", None).endswith("TOTALS: 7"))

    def test_only_carloss_key_reads_the_vantura_board_and_a_failure_is_no_block(self):
        office = mock.Mock(owner="Somebody")
        with mock.patch.object(VT, "for_day", side_effect=AssertionError("read")), \
             mock.patch("automations.icd_alerts.knocks_post._teams_for", return_value="RAF"):
            self.assertEqual(P._text_teams("raf", office, dt.date(2026, 11, 19)), "RAF")
        with mock.patch.object(VT, "for_day", side_effect=RuntimeError("sheets")):
            self.assertIsNone(P._text_teams("carlos-b2batt", office, dt.date(2026, 11, 19)))
        VT._CACHE.clear()
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        side_effect=RuntimeError("429")):
            self.assertIsNone(VT.for_day(dt.date(2026, 11, 19), log=lambda m: None))
        VT._CACHE.clear()


if __name__ == "__main__":
    unittest.main()
