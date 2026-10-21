import datetime as dt
import unittest
from unittest import mock

from automations.lumen_owners import board as B

MON = dt.date(2026, 10, 19)
WEEK = [MON + dt.timedelta(days=i) for i in range(7)]
WE = dt.date(2026, 10, 25)


def _cands(name, aliases):
    return {" ".join(name.casefold().split())}


def _week(we, per_owner):
    """{owner: [mon..sun]} -> the pull_programs shape for that week."""
    days = [we - dt.timedelta(days=6 - i) for i in range(7)]
    return {o: {"NewInternet": {d: v for d, v in zip(days, vals) if v},
                "Total": {d: 2 * v for d, v in zip(days, vals) if v}}
            for o, vals in per_owner.items()}


class BoardTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch("automations.org_sales_board.captainship."
                       "_candidates_for_name", _cands)
        p.start()
        self.addCleanup(p.stop)
        self.weeks = {WE: _week(WE, {"amy": [3, 1, 0, 0, 0, 0, 0],
                                     "bob": [1, 0, 0, 0, 0, 0, 0]})}
        for k, base in ((1, 4), (2, 2), (3, 2), (4, 0)):
            we = WE - dt.timedelta(days=7 * k)
            self.weeks[we] = _week(we, {"amy": [base, 1, 1, 1, 1, 1, 0],
                                        "bob": [0, 0, 0, 0, 0, 0, 0]})

    def test_history_roundtrip(self):
        lines = B.weeks_to_history(self.weeks, dt.date(2026, 1, 1))
        self.assertEqual(lines[0][:3], ["week_ending", "metric", "owner"])
        back = B.history_to_weeks([[str(c) for c in ln] for ln in lines])
        self.assertEqual(back[WE]["amy"]["NewInternet"], {MON: 3, WEEK[1]: 1})
        self.assertEqual(set(back), set(self.weeks))

    def test_history_drops_old_weeks(self):
        lines = B.weeks_to_history(self.weeks, WE - dt.timedelta(days=7))
        self.assertEqual({ln[0] for ln in lines[1:]},
                         {WE.isoformat(), (WE - dt.timedelta(days=7)).isoformat()})

    def test_box_numbers(self):
        n = B.box_numbers(["Bob", "Amy"], self.weeks, WEEK, WEEK[1],
                          "NewInternet", {})
        self.assertEqual([o for o, _, _ in n["owners"]], ["Amy", "Bob"])
        self.assertEqual(n["team_days"][:2], [4, 1])
        self.assertEqual(n["shown"], [True, True] + [False] * 5)
        self.assertEqual(n["last_days"][0], 4)
        self.assertEqual(n["avg_days"][0], 2)           # (4+2+2+0)/4
        amy = n["owners"][0][1]
        self.assertEqual(amy[WE], 4)
        self.assertIsNone(amy[WE - dt.timedelta(days=7 * 5)])   # never pulled

    def test_grid_blanks_future_days_and_compares_wtd(self):
        g, spans = B.build_grid(["Amy", "Bob"], self.weeks, WEEK, WEEK[1], {})
        self.assertEqual([m for m, _, _ in spans], ["NewInternet", "Total"])
        top, bottom = spans[0][1], spans[0][2]
        text = {(r, c): v for (r, c), (v, _) in g.cells.items()
                if top <= r <= bottom}
        row = next(r for (r, c), v in text.items() if v == "vs Prior Week")
        self.assertAlmostEqual(text[(row, 2)], 0.0)       # Mon 4 vs 4
        self.assertEqual(text[(row, 4)], "")             # Wednesday: no 0%
        self.assertAlmostEqual(text[(row, 9)], (5 - 5) / 5)   # Mon+Tue vs Mon+Tue
        ps = next(r for (r, c), v in text.items() if v == "Fiber - New Internet")
        self.assertEqual(text[(ps, 4)], "")              # Wednesday still ahead
        self.assertEqual(text[(ps, 9)], 5)
        dash = [v for v in text.values() if v == "–"]
        self.assertTrue(dash)                            # missing weeks = dash


if __name__ == "__main__":
    unittest.main()
