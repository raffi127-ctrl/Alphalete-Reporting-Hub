"""CS tab finish: FIRST & SECOND counts, training bonuses, borders .

  python -m unittest automations.vantura_payroll.test_cs_tidy
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.vantura_payroll import cs_tidy as T

WK = dt.date(2026, 11, 22)
OL = [["Order Date", "Rep", "Line Status", "DSI #", "Type"],
      ["11/18/2026", "Nora Delta", "Shipped", "D1", "Port"],
      ["11/18/2026", "Nora Delta", "Shipped", "D1", "Port"],
      ["11/21/2026", "Nora Delta", "Cancelled", "D2", "Port"],       # cancelled: out
      ["11/21/2026", "Nora Delta", "Active", "D3", "New"],           # new number: not an app
      ["11/23/2026", "Nora Delta", "", "D4", "Port"],                # after the week
      ["11/13/2026", "Test Middle Alpha Beta", "Active", "D5", "Port"],
      ["11/13/2026", "Omar Bravo", "Active", "D6", "Port"]]
ADJ = [["Week", "Rep", "Type", "Amount", "Label"],
       ["11.15", "Test Middle Alpha Beta", "Bonus", "800", "Training bonus 1 & 2 "],
       ["11.15", "Test Middle Alpha Beta", "Bonus", "200", "Shadow pay "],
       ["11.15", "Rita Bravo Cole", "Bonus", "400", "1st training bonus "],
       ["11.22", "Nora Delta", "Bonus", "400", "1st training bonus "],
       ["9.2", "Old Rep", "Bonus", "300", "Training bonus one - partial ($100 left to qualify)"]]


class Counts(unittest.TestCase):
    def test_orders_are_dsis_and_apps_are_port_lines(self):
        got = T.order_counts(OL, ["Nora Delta", "Test Alpha", "Rita Bravo Cole"], WK)
        self.assertEqual(got, {"Nora Delta": (1, 2), "Test Alpha": (1, 1),
                               "Rita Bravo Cole": (0, 0)})       # not Omar Bravo's

    def test_a_missing_column_raises(self):
        with self.assertRaises(ValueError):
            T.order_counts([["Order Date", "Rep"]], ["X Y"], WK)


class Bonuses(unittest.TestCase):
    def test_prior_weeks_only(self):
        got = T.training_bonuses(ADJ, ["Test Alpha", "Rita Bravo Cole", "Nora Delta", "Old Rep"], WK)
        self.assertEqual(got, {"Test Alpha": "#1 and #2", "Rita Bravo Cole": "#1",
                               "Nora Delta": "None", "Old Rep": "#1 (partial)"})

    def test_labels(self):
        f = T.bonus_numbers
        self.assertEqual(f("Training bonus one and two"), {1: "full", 2: "full"})
        self.assertEqual(f("Second training bonus"), {2: "full"})
        self.assertEqual(f("1st training bonus $400 + shadow pay $175 (set total to $575)"), {1: "full"})
        self.assertEqual(f("Remainder of training bonus one and training bonus two"), {1: "full", 2: "full"})
        self.assertEqual(f("Training Bonus"), {0: "full"})
        self.assertEqual(f("First sale bonus"), {})
        self.assertEqual(f("Shadow pay "), {})

    def test_partial_then_full_reads_full(self):
        adj = [ADJ[0], ["9.13", "Old Rep", "Bonus", "300", "Training bonus one - partial"],
               ["9.2", "Old Rep", "Bonus", "500", "Remainder of training bonus one and training bonus two"]]
        self.assertEqual(T.training_bonuses(adj, ["Old Rep"], WK), {"Old Rep": "#1 and #2"})

    def test_trailing_zero_weeks(self):
        self.assertEqual(T.week_date("9.2", WK), dt.date(2026, 9, 20))
        self.assertEqual(T.week_date("8.3", WK), dt.date(2026, 8, 30))
        self.assertEqual(T.week_date("11.1", WK), dt.date(2026, 11, 1))
        self.assertIsNone(T.week_date("11.29", WK) if T.week_date("11.29", WK) and
                          T.week_date("11.29", WK).year == 2026 else None)


class Layout(unittest.TestCase):
    MAT = [["Pick", "11.22"], [], ["Rep", "Brought In"], ["A B", 1], ["TOTAL", 1], [], [],
           ["ACTIVE REPS - NO REVENUE", "", "REVENUE - NOT ACTIVE"], ["E A", "", "C C", 429], ["", "", "R B", 1739],
           [], [], ["FIRST & SECOND WEEK PAYCHECKS"], ["Rep", "Order Count", "Total Apps"], ["Nora Delta", 0, 0]]

    def test_panels(self):
        p = T.find_panels(self.MAT)
        self.assertEqual(p, {"total": 4, "norev": (7, 1), "revnot": (7, 2), "fs": (12, 1)})

    def test_borders_wiped_below_total_then_redrawn(self):
        reqs = T.border_requests(9, T.find_panels(self.MAT), 300, fs_cols=4)
        wipe = reqs[0]["updateBorders"]
        self.assertEqual((wipe["range"]["startRowIndex"], wipe["range"]["endRowIndex"],
                          wipe["range"]["endColumnIndex"]), (5, 300, 5))
        self.assertNotIn("top", wipe)                        # TOTAL keeps its bottom edge
        boxes = [r["updateBorders"]["range"] for r in reqs[1:]]
        self.assertEqual([(b["startRowIndex"], b["endRowIndex"], b["startColumnIndex"], b["endColumnIndex"])
                          for b in boxes], [(7, 9, 0, 1), (7, 10, 2, 4), (12, 15, 0, 4)])

    def test_no_total_means_no_requests(self):
        self.assertEqual(T.border_requests(9, T.find_panels([["x"]]), 50, fs_cols=3), [])


if __name__ == "__main__":
    unittest.main()
