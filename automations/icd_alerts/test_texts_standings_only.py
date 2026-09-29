"""A text group can take the sales scoreboard ONLY -- no knock board, no gap
list (Drew Tepper 2026-09-28, via Megan)."""
import json
import unittest

from automations.icd_alerts import knocks_post as KP, post as P


class _Book:
    def __init__(self, rows): self._rows = rows
    def worksheet(self, name): return self
    def get_all_values(self): return self._rows


class StandingsOnlyTexts(unittest.TestCase):
    def test_the_flag_survives_the_approval_reader(self):
        hdr = [""] * (P.CH_TX_APPROVED + 1)
        row = [""] * (P.CH_TX_APPROVED + 1)
        row[P.CH_OFFICE] = "drew"
        row[P.CH_TX_APPROVED_JSON] = json.dumps([
            {"group": "Precision Mastermind", "cadence_min": 60, "standings_only": True},
            {"group": "Other", "cadence_min": 30}])
        row[P.CH_TX_APPROVED] = "TRUE"
        got = P.approved_texts(_Book([hdr, row]))["drew"]
        self.assertTrue(got[0]["standings_only"])
        self.assertFalse(got[1]["standings_only"])

    def test_knock_boards_skip_a_standings_only_group(self):
        texts = [{"group": "Precision Mastermind", "standings_only": True},
                 {"group": "Other"}]
        self.assertEqual([t["group"] for t in KP.boards_for_texts(texts)], ["Other"])
        self.assertEqual(KP.boards_for_texts(None), [])


if __name__ == "__main__":
    unittest.main()


class TheBoardCanRideLessOftenThanTheList(unittest.TestCase):
    """Maxamad 2026-09-28: gap list to the group every 15, the board every 30."""

    def test_no_setting_means_the_board_every_time(self):
        import datetime as dt
        now = dt.datetime(2026, 9, 29, 14, 15)
        self.assertTrue(KP.board_rides({"cadence_min": 15}, now - dt.timedelta(minutes=15), now))
        self.assertTrue(KP.board_rides({"cadence_min": 15, "board_min": 0}, now, now))

    def test_board_every_30_on_a_15_minute_list(self):
        import datetime as dt
        now = dt.datetime(2026, 9, 29, 14, 15)
        d = {"cadence_min": 15, "board_min": 30}
        self.assertTrue(KP.board_rides(d, None, now))                                # first ever
        self.assertFalse(KP.board_rides(d, now - dt.timedelta(minutes=15), now))     # :00 board, :15 list only
        self.assertTrue(KP.board_rides(d, now - dt.timedelta(minutes=30), now))      # :30 board again

    def test_the_setting_survives_the_approval_reader(self):
        hdr = [""] * (P.CH_TX_APPROVED + 1); row = [""] * (P.CH_TX_APPROVED + 1)
        row[P.CH_OFFICE] = "maxamad"
        row[P.CH_TX_APPROVED_JSON] = json.dumps([{"group": "Maximal Leaders", "cadence_min": 15, "board_min": 30}])
        row[P.CH_TX_APPROVED] = "TRUE"
        got = P.approved_texts(_Book([hdr, row]))["maxamad"][0]
        self.assertEqual((got["cadence_min"], got["board_min"]), (15, 30))
