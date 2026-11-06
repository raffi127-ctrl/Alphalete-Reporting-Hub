"""Raf's Eco text copies his sales board's headcount block, like Lucy 1."""
import datetime as dt
import sys
import types
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
    def test_raf_text_comes_from_his_eco(self):
        """Megan 2026-11-06: Raf's room gets the board from his Eco only."""
        from automations.alphalete_sales_board import config as C
        self.assertNotIn("raf", P.TEXT_PAUSED)
        self.assertNotIn(C.GROUP_KNOCKING, C.LIVE_GROUPS)

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


class NoRowNote(unittest.TestCase):
    """Eve 2026-11-06: the Eco text carries Lucy 1's no-row footer too."""

    def _reads(self, sales):
        ws = mock.Mock()
        ws.get_all_values.return_value = [["x"]]
        # guests needs the browser lib, which a test box may not have; Raf's
        # guest reps are calc's business, so a stand-in that names none.
        fake_guests = types.ModuleType("automations.total_knocks.guests")
        fake_guests.guest_for = lambda host, name: None
        fill = "automations.alphalete_sales_board.fill."
        with mock.patch.dict(sys.modules,
                             {"automations.total_knocks.guests": fake_guests}), \
                mock.patch(fill + "open_tab", return_value=ws), \
                mock.patch(fill + "board_stats", return_value=STATS), \
                mock.patch(fill + "board_names", return_value=["Ana Griffin"]), \
                mock.patch("automations.alphalete_sales_board.aliases.load",
                           return_value={}):
            return P.board_reads("raf", DAY, sales, log=lambda *_: None)

    def test_rep_with_no_row_is_named_jd_is_not(self):
        stats, unlisted = self._reads({"ANA GRIFFIN": {"Int": 1},
                                       "BO KELVINTON": {"NL": 1},
                                       "JOSHUA MASCORRO": {"NL": 2},
                                       "ZED ZERO": {"Int": 0}})
        self.assertEqual(stats, STATS)
        self.assertEqual(unlisted, ["BO KELVINTON"])

    def test_footer_reads_like_lucy_1(self):
        from automations.alphalete_sales_board import notify as N
        self.assertEqual(P.no_row_note([]), [])
        self.assertEqual(P.no_row_note(["BO KELVINTON"])[1],
                         "%s Bo Kelvinton sold with no row on this week's "
                         "board - counted above, not on the board yet." % N.FIRE)


if __name__ == "__main__":
    unittest.main()
