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


class WeekBlock(unittest.TestCase):
    """Carlos 2026-11-19: from 8:30pm the text adds each team's week."""

    def _grid_with_days(self):
        g = _grid()
        # Stefany (Diego): Mon 3, Tue 2, Wed 1, Thu 9 (today's cell is ignored)
        g[4][4:8] = ["3", "2", "1", "9"]
        # Nathaly (Cinthya): Mon T, Tue 4
        g[6][4:6] = ["T", "4"]
        return g

    def test_board_days_before_today_plus_todays_live_numbers(self):
        thu = dt.date(2026, 11, 19)
        book = VT.from_grid(self._grid_with_days(), "NDS Sales Board", thu)
        self.assertEqual(book.week_before, {"Diego": 6, "Cinthya": 4})
        lines = VT.week_lines(book, [("Nathaly Benitez", 3), ("Nick Smedra", 1),
                                     ("New Guy", 2)], thu)
        self.assertEqual(lines, ["", "Week (Mon-Thu):", "Cinthya: 7 \U0001F947",
                                 "Diego: 6", "Direct Hit: 1", "Unassigned: 2"])

    def test_only_from_830pm_central(self):
        from zoneinfo import ZoneInfo
        ct = ZoneInfo("America/Chicago")
        self.assertFalse(VT.week_due(dt.datetime(2026, 11, 19, 20, 29, tzinfo=ct)))
        self.assertTrue(VT.week_due(dt.datetime(2026, 11, 19, 20, 30, tzinfo=ct)))
        self.assertTrue(VT.week_due(dt.datetime(2026, 11, 19, 23, 50, tzinfo=ct)))
        self.assertFalse(VT.week_due(dt.datetime(2026, 11, 19, 14, 0, tzinfo=ct)))

    def test_the_text_gets_it_only_for_carlos_and_only_when_due(self):
        thu = dt.date(2026, 11, 19)
        book = VT.from_grid(self._grid_with_days(), "NDS Sales Board", thu)
        office = mock.Mock(campaign="nds")
        sales = {"NATHALY BENITEZ": {"NL": 2, "Air": 1, "Int Up": 3}}
        with mock.patch.object(VT, "week_due", return_value=True):
            block = P._week_team_block("carlos-b2batt", thu, office, sales, None, book)
            self.assertIn("Cinthya: 7", block)            # 4 board + 3 live (no upgrades)
            self.assertEqual(P._week_team_block("raf", thu, office, sales, None, book), "")
        with mock.patch.object(VT, "week_due", return_value=False):
            self.assertEqual(P._week_team_block("carlos-b2batt", thu, office, sales, None, book), "")


if __name__ == "__main__":
    unittest.main()
