"""teams_box.last_week_rows: the Teams box as it stood last week, rebuilt off
the rep rows' Last Wk column (Carlos 2026-11-23, a Monday: "send a screenshot
of the team totals for last week on there")."""
import unittest

from automations.sales_boards import teams_box as T


def grid():
    g = [[""] * 46 for _ in range(52)]

    def put(r, **cells):                      # r 1-based; cells by column letter
        for col, v in cells.items():
            i = 0
            for ch in col:
                i = i * 26 + ord(ch) - 64
            g[r - 1][i - 1] = v
    put(2, A="WE", B="11.29")
    put(4, A="#", B="REP", C="Current Week", D="Last Wk", L="Campaign", O="Team",
        AQ="Term?", AR="No HC?")
    put(5, B="New Guy", D="0", L="NDS", O="")
    put(6, B="Ann", D="9", L="NDS", O="Red", AQ="0")
    put(7, B="Bob", D="12", L="NDS", O="Blue", AQ="0")
    put(8, B="Cal", D="5", L="NDS", O="Red", AQ="0")
    put(9, B="Gone Rep", D="3", L="NDS", O="Blue", AQ="1")     # terminated: out
    put(10, B="Verizon Vic", D="7", L="Verizon", O="Red", AQ="0")   # other campaign: out
    put(11, B="AT&T NDS", D="29", L="NDS", AQ="0")
    put(12, B="Last Week", D="WE 11.22")
    put(20, B="Teams — Current Week", C="Apps", D="Total Head Count", E="Leaders",
        F="Entry Level", G="In Training", H="Sales Avg by Rep")
    put(21, B="AT&T NDS", C="0", D="4", E="3", F="0", G="1", H="0.0")
    put(22, B="Blue", C="0", D="1", E="1", F="0", G="0", H="0.0")
    put(23, B="Red", C="0", D="2", E="2", F="0", G="0", H="0.0")
    put(24, B="Unaccounted For", C="0", D="1", E="0", F="0", G="1", H="0.0")
    return g


class LastWeek(unittest.TestCase):
    def test_apps_off_last_wk_ranked_with_the_box_filters(self):
        week, rows = T.last_week_rows(grid())
        self.assertEqual(week, "WE 11.22")
        self.assertEqual([r[0] for r in rows], ["AT&T NDS", "Red", "Blue", "Unaccounted For"])
        apps = {l: s["Apps"] for l, _t, s in rows}
        self.assertEqual(apps, {"AT&T NDS": "26", "Red": "14", "Blue": "12",
                                "Unaccounted For": "0"})
        self.assertTrue(rows[0][1])                              # the campaign row is the total

    def test_head_counts_are_the_live_box_and_avg_is_apps_over_head_count(self):
        _w, rows = T.last_week_rows(grid())
        red = next(s for l, _t, s in rows if l == "Red")
        self.assertEqual((red["Total Head Count"], red["Leaders"]), ("2", "2"))
        self.assertEqual(red["Sales Avg by Rep"], "7.0")


if __name__ == "__main__":
    unittest.main()
