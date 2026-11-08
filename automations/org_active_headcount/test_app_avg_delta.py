"""The App Avg week-over-week table: same cells as the delta box, ranked.

    python -m unittest automations.org_active_headcount.test_app_avg_delta
"""
import unittest

from automations.org_active_headcount import app_avg_delta as A
from automations.org_active_headcount.test_app_avg import _hc


def _grid():
    g = _hc()
    dh = next(i for i, r in enumerate(g) if r and r[0].startswith("All Campaings") and "by" in r[2])
    g[dh + 2][5:8] = ["5.0", "6.0", "-16.67%"]        # Rafael
    g[dh + 3][5:8] = ["9.4", "9.4", "0.00%"]          # Ana
    g[dh + 4][5:8] = ["7.2", "7.7", "-6.49%"]         # totals
    return g


class AppAvgTable(unittest.TestCase):
    def test_ranked_by_this_week_with_the_cells_the_tab_shows(self):
        caption, rows, totals = A.table(_grid())
        self.assertEqual(caption, "by Wednesday")
        self.assertEqual(rows, [("Ana Griffin", "9.4", "9.4", "0.00%"),
                                ("Rafael Hidalgo", "5.0", "6.0", "-16.67%")])
        self.assertEqual(totals, ("Totals", "7.2", "7.7", "-6.49%"))

    def test_a_tie_goes_by_name_and_a_blank_ranks_last(self):
        self.assertEqual(sorted([("Zed", "7.0", "", ""), ("", "", "", ""), ("Abe", "7.0", "", "")],
                                key=A._rank_key)[0][0], "Abe")
        self.assertEqual(A._rank_key(("x", "", "", ""))[0], 0.0)

    def test_a_tab_without_the_columns_alerts(self):
        g = _hc()
        dh = next(i for i, r in enumerate(g) if r and r[0].startswith("All Campaings") and "by" in r[2])
        g[dh][5] = ""
        with self.assertRaises(ValueError):
            A.table(g)


if __name__ == "__main__":
    unittest.main()
