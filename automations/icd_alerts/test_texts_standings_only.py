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
