"""The BOX pass may only clear the board when the order log holds the day.

2026-09-16: the 09:30 fail-open ran with Tableau still short of Tuesday, read
zero BOX sales and blanked eight that Slack had filled.

    python -m unittest automations.vantura_orderlog_sales.test_fill_plan -v
"""
from __future__ import annotations

import unittest
import unittest.mock

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


class HomeCampaignTest(unittest.TestCase):
    """Nico's sales follow his row's col-L label, not a hardcoded campaign
    (2026-09-19: row re-filed B2B, BOX pass flagged 5 sales unmatched).
    Since the three-board split each campaign's rows come off its own tab,
    so home_campaigns looks across {campaign: grid}."""

    GRIDS = {"B2B": "b2b-grid", "BOX": "box-grid"}

    def test_row_label_wins(self):
        with unittest.mock.patch.object(run, "campaign_rows",
                                        side_effect=lambda g, c: (
                                            {"nico murrugarra": 13}
                                            if c == "B2B" else {})):
            self.assertEqual(run.home_campaigns(self.GRIDS)["nico murrugarra"],
                             "B2B")

    def test_no_row_keeps_fallback(self):
        with unittest.mock.patch.object(run, "campaign_rows",
                                        return_value={}):
            self.assertEqual(run.home_campaigns(self.GRIDS)["nico murrugarra"],
                             "BOX")

    def test_each_campaign_is_looked_up_on_its_own_grid(self):
        """The BOX tab's grid is asked for BOX rows, the main tab's for B2B —
        never the other way round."""
        seen = []

        def rows(g, c):
            seen.append((g, c))
            return {}

        with unittest.mock.patch.object(run, "campaign_rows", side_effect=rows):
            run.home_campaigns(self.GRIDS)
        self.assertEqual(sorted(seen), [("b2b-grid", "B2B"), ("box-grid", "BOX")])

    def test_a_missing_grid_is_skipped(self):
        with unittest.mock.patch.object(run, "campaign_rows",
                                        return_value={}):
            self.assertEqual(run.home_campaigns({"BOX": "box-grid"})
                             ["nico murrugarra"], "BOX")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class D2DRepsNotFlaggedTest(unittest.TestCase):
    """Carlos 2026-09-30: Verizon (D2D board) reps stay off the Sales Board —
    their AT&T log sales are not a 'no row' hole."""

    def test_d2d_rep_is_not_unmatched(self):
        d2d = {"giovanni monreal": 18, "luis valenciano": 12}
        keep, on_d2d = run.split_d2d(
            [("giovanni monreal", 5), ("luis valenciano", 2),
             ("nobody anywhere", 1)], d2d)
        self.assertEqual(keep, [("nobody anywhere", 1)])
        self.assertEqual([k for k, _n in on_d2d],
                         ["giovanni monreal", "luis valenciano"])
