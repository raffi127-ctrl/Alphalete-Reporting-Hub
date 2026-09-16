"""The BOX pass may only clear the board when the order log holds the day.

2026-09-16: the 09:30 fail-open ran with Tableau still short of Tuesday, read
zero BOX sales and blanked eight that Slack had filled.

    python -m unittest automations.vantura_orderlog_sales.test_fill_plan -v
"""
from __future__ import annotations

import unittest

from automations.vantura_orderlog_sales import run

COL = 6                                            # TUE


def _grid():
    g = [[""] * 12 for _ in range(4)]
    g[1][run.NAME_COL - 1], g[1][COL - 1] = "Esmeralda Gonzalez", "3"
    g[2][run.NAME_COL - 1], g[2][COL - 1] = "Joelle Barajas", "1"
    g[3][run.NAME_COL - 1] = "Tara Lynn Ecklof"
    return g


def _result(covered, matched):
    rows = {"esmeralda gonzalez": 2, "joelle barajas": 3,
            "tara lynn ecklof": 4}
    return {"campaign": "BOX", "col": COL, "rows": rows,
            "matched": matched, "covered": covered}


class BoxFillPlanTest(unittest.TestCase):
    def test_covered_day_is_authoritative(self):
        plan = run.fill_plan(_grid(), _result(True, {"esmeralda gonzalez": 2}))
        self.assertEqual(sorted((a1, new) for _r, a1, _c, new, _n in plan),
                         [("F2", "2"), ("F3", "(blank)")])

    def test_empty_fail_open_day_clears_nothing(self):
        self.assertEqual(run.fill_plan(_grid(), _result(False, {})), [])

    def test_fail_open_still_raises(self):
        plan = run.fill_plan(_grid(), _result(False, {"esmeralda gonzalez": 1,
                                                      "tara lynn ecklof": 2}))
        self.assertEqual([(a1, new) for _r, a1, _c, new, _n in plan],
                         [("F4", "2")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
