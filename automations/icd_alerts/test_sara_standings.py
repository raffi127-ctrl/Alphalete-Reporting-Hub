"""Frank Matos's Sara list (2026-11-09): per-rep credit checks + office total,
texted to his group whenever a count moves; no knock board rides to it."""
import datetime as dt
import unittest

from automations.icd_alerts import post as P
from automations.icd_alerts import knocks_post as KP


class SaraStandings(unittest.TestCase):
    def test_list_shape(self):
        txt = P.sara_standings_text({"Mekhi Henry": 4, "Jamal": 3, "Willie": 1, "Albi": 4, "Nobody": 0},
                                    now=dt.datetime(2026, 11, 9, 15, 45))
        self.assertEqual(txt.splitlines()[0], "SARA CHECKS — 3:45 PM")
        self.assertEqual(txt.splitlines()[1:5], ["ALBI 4", "MEKHI HENRY 4", "JAMAL 3", "WILLIE 1"])
        self.assertTrue(txt.endswith("TOTAL: 12 IN SARA"))
        self.assertNotIn("NOBODY", txt)

    def test_never_blank(self):
        self.assertEqual(P.sara_standings_text({}), "")
        self.assertEqual(P.sara_standings_text({"A": 0}), "")

    def test_moved_only_when_a_count_changes(self):
        self.assertTrue(P._sara_moved({"A": 2}, {"A": 1}))
        self.assertTrue(P._sara_moved({"A": 1}, {}))
        self.assertFalse(P._sara_moved({"A": 2}, {"A": 2}))

    def test_sara_group_gets_no_knock_board(self):
        texts = [{"group": "PEAK A PLAYERS", "sara_standings": True}, {"group": "Other"}]
        self.assertEqual([t["group"] for t in KP.boards_for_texts(texts)], ["Other"])


if __name__ == "__main__":
    unittest.main()
