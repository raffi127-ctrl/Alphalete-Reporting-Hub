"""Raf's Eco text copies his sales board's headcount block, like Lucy 1."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import post as P

DAY = dt.date(2026, 11, 5)
STATS = [("Total Reps in the Field / Board / Zero", "46"),
         ("Reps that got on the Board", "16")]


class BoardHeadcount(unittest.TestCase):
    def test_other_offices_keep_knocks_count(self):
        self.assertIsNone(P.board_headcount("aiden", DAY, log=lambda *_: None))

    def test_raf_reads_the_sales_board(self):
        ws = mock.Mock()
        ws.get_all_values.return_value = [["x"]]
        with mock.patch("automations.alphalete_sales_board.fill.open_tab",
                        return_value=ws), \
             mock.patch("automations.alphalete_sales_board.fill.board_stats",
                        return_value=STATS) as bs:
            self.assertEqual(P.board_headcount("raf", DAY, log=lambda *_: None), STATS)
        bs.assert_called_once_with(ws, [["x"]], DAY)

    def test_raf_read_failure_drops_the_block(self):
        with mock.patch("automations.alphalete_sales_board.fill.open_tab",
                        side_effect=RuntimeError("no tab")):
            self.assertEqual(P.board_headcount("raf", DAY, log=lambda *_: None), [])


class RafEcoText(unittest.TestCase):
    def test_raf_text_is_paused(self):
        self.assertIn("raf", P.TEXT_PAUSED)

    def test_teams_reach_the_eco_board(self):
        class Book:
            teams = ["Ceaseless", "Hashiras"]
            def team_for(self, name):
                return {"Ana Griffin": "Ceaseless"}.get(name)
        out = P.scoreboard_text({"ANA GRIFFIN": {"Int": 2},
                                 "JOSHUA MASCORRO": {"NL": 1}}, [],
                                show=lambda r: r.title(), teams=Book())
        self.assertIn("Ceaseless: 2", out)
        self.assertIn("Hashiras: 0", out)
        self.assertIn("Unassigned: 1", out)


if __name__ == "__main__":
    unittest.main()
