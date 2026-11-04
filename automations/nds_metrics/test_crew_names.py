"""crew_names(): the static GUEST_REPS roster + Carlos + every rep on the
live NDS Sales Board, de-duplicated; the static list alone when the board
cannot be read (Carlos 2026-11-03: the Revenue Board showed two reps)."""
import sys
import types
import unittest

from automations.nds_metrics import run as R
from automations.total_knocks import guests

MOD = "automations.vantura_slack_sales.run"


def _fake_board(names, fail=False):
    m = types.ModuleType(MOD)
    m.NAME_COL = 2
    m._cell = lambda g, r, c: g[r - 1][c - 1]
    if fail:
        def board_grid(campaign="B2B"):
            raise RuntimeError("no sheet today")
    else:
        def board_grid(campaign="B2B"):
            return None, [["", n] for n in names]
    m.board_grid = board_grid
    m.campaign_rows = lambda g, campaign: {n.lower(): i + 1 for i, n in enumerate(names)}
    return m


class CrewNames(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get(MOD)

    def tearDown(self):
        if self._saved is not None:
            sys.modules[MOD] = self._saved
        else:
            sys.modules.pop(MOD, None)

    def test_board_reps_join_the_roster(self):
        sys.modules[MOD] = _fake_board(["Annett Michell Climaco", "Elisa Diaz-Garcia",
                                        "Nicholas Smedra", "", "Carlos Hidalgo"])
        out = R.crew_names(log=lambda *a: None)
        self.assertIn("Annett Michell Climaco", out)
        self.assertIn("Elisa Diaz-Garcia", out)
        for n in guests.roster("Rafael Hidalgo", "Carlos Hidalgo"):
            self.assertIn(n, out)
        self.assertEqual(out.count("Nicholas Smedra"), 1)      # de-duplicated
        self.assertEqual(out.count("Carlos Hidalgo"), 1)
        self.assertNotIn("", out)

    def test_board_unreadable_falls_back_to_the_static_roster(self):
        sys.modules[MOD] = _fake_board([], fail=True)
        said = []
        out = R.crew_names(log=said.append)
        self.assertEqual(out, guests.roster("Rafael Hidalgo", "Carlos Hidalgo") + ["Carlos Hidalgo"])
        self.assertTrue(any("static roster only" in s for s in said))


if __name__ == "__main__":
    unittest.main()
