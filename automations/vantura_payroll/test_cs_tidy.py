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


class Rates(unittest.TestCase):
    RATES = [["", "Base", "Override", "Rate"], ["Gold Rep", "0.5", "", "50.00%"], ["Vet Rep", "0.75", "", "0.75"]]
    ADJ = [["Week", "Rep", "Type", "Amount", "Label"],
           ["11.22", "Nora Delta", "Bonus", "9.15", "45% pay - 10 apps last week (Carlos 11/24)"],
           ["11.22", "Low Rep", "Bonus", "-42.9", "Paid at 30% (Carlos 11/24)"],
           ["11.15", "Rita Bravo", "Bonus", "50", "50% pay - 14 apps last week"],        # another week
           ["11.22", "Rita Bravo", "Bonus", "400", "2nd training bonus (Carlos 11/24)"],
           ["11.22", "Gone Rep", "REMOVEALL", "", "No pay week 11.22"]]

    def test_rates_tab_then_this_weeks_row(self):
        got = T.rates_for(["Gold Rep", "Vet Rep", "Nora Delta", "Low Rep", "Rita Bravo", "Gone Rep"],
                          self.RATES, self.ADJ, WK)
        self.assertEqual(got, {"Gold Rep": 0.5, "Vet Rep": 0.75, "Nora Delta": 0.45, "Low Rep": 0.3,
                               "Rita Bravo": 0.4, "Gone Rep": 0.0})

    def test_labels_that_are_not_rates(self):
        for s in ("Level 2 bonus (5% of revenue)", "Set total to $500", "2nd training bonus", ""):
            self.assertIsNone(T.week_rate(s), s)

    def test_levels_due_are_leaders_only_last_mon_to_sun(self):
        board = [["#", "REP", "Leadership Status"], ["1", "Rosa Top", "Level 1"], ["2", "Nat Mid", "Level 2"],
                 ["3", "New Rep", "Entry Level"], ["4", "Near Miss", "Level 1"], ["", "AT&T NDS", ""]]
        wd = [["Rosa Top|11.22", "X", "2", "4", "4", "4", "X", ""], ["Nat Mid|11.22", "4", "0", "4", "4", "", "", ""],
              ["New Rep|11.22", "10", "", "", "", "", "", ""], ["Near Miss|11.22", "9", "0", "", "", "", "", ""],
              ["Near Miss|11.15", "20", "", "", "", "", "", ""]]
        due = T.levels_due(board, wd, WK)
        self.assertEqual(due, {"Rosa Top": (14, 0.5), "Nat Mid": (12, 0.45)})
        self.assertEqual(T.levels_report(due, {"Rosa Top": 0.5, "Nat Mid": 0.4}),
                         "Rosa Top 14 apps -> 50% ok; Nat Mid 12 apps -> 45% NOT APPLIED (paid 40%)")

    def test_trailing_zero_week_key(self):
        board = [["#", "REP", "Leadership Status"], ["1", "Rosa Top", "Level 1"]]
        self.assertEqual(T.levels_due(board, [["Rosa Top|8.30", "10", "", "", "", "", "", ""]], dt.date(2026, 8, 30)),
                         {"Rosa Top": (10, 0.45)})

    def test_rate_column_goes_in_at_e(self):
        reqs = T.rate_requests(7, 27)
        self.assertEqual(reqs[0]["insertDimension"]["range"]["startIndex"], 4)
        box = [r["updateBorders"]["range"] for r in reqs if "updateBorders" in r][0]
        self.assertEqual((box["startRowIndex"], box["endRowIndex"], box["endColumnIndex"]), (2, 28, 6))


class Payout(unittest.TestCase):
    def row(self, rep, sale="", desc="", cust="", amt="", com=""):
        r = [""] * 15
        r[6], r[7], r[9], r[12], r[13], r[14] = rep, sale, desc, cust, amt, com
        return r

    def mat(self):
        R = self.row
        return [[""] * 15, [""] * 15, R("REP Name"),
                R("Nat Mid", 46340, "OOF", "X", 213, 85.2), R("Nat Mid", 46340, "Port Line", "X", 10, 4),
                R("Nat Mid", desc="45% pay - 12 apps last week", com=11.15),
                R("Nat Mid", desc="2nd training bonus", com=400), R("", cust="", amt="", com=""),
                R("REP Name"), R("Vet", 46340, "OOF", "Y", 213, 159.75), R("Vet", 46340, "OOF", "Z", 50, 0)]

    def test_level_lines_restated_and_the_bonus_row_dropped(self):
        m = self.mat()
        plan = T.payout_plan(m)
        self.assertEqual(plan["drop"], [5])                          # the training bonus stays
        self.assertEqual(plan["comm"], {3: 95.85, 4: 4.5})
        self.assertEqual(plan["pct"], {3: 0.45, 4: 0.45, 9: 0.75, 10: 0.0})
        self.assertEqual(plan["hdr"], [2, 8])
        self.assertTrue(T.plan_ties(m, plan))

    def test_a_plan_that_does_not_tie_is_refused(self):
        m = self.mat()
        m[5][14] = 50
        self.assertFalse(T.plan_ties(m, T.payout_plan(m)))
        plain = T.payout_plan(m, restate=False)                      # then the lines show what they really paid
        self.assertEqual((plain["drop"], plain["comm"], plain["pct"][3]), ([], {}, 0.4))

    def test_only_itemized_columns_are_deleted_bottom_up(self):
        reqs = T.pct_requests(3, {"drop": [5, 20]}, 100)
        d = [r["deleteRange"]["range"] for r in reqs if "deleteRange" in r]
        self.assertEqual([x["startRowIndex"] for x in d], [20, 5])
        self.assertEqual({(x["startColumnIndex"], x["endColumnIndex"]) for x in d}, {(6, 15)})
        self.assertEqual([r["insertDimension"]["range"]["startIndex"] for r in reqs if "insertDimension" in r], [14])


class Gap(unittest.TestCase):
    def test_only_horizontal_lines_go_below_the_header(self):
        a, b = [r["updateBorders"] for r in T.gap_requests(1, 900, 17)]
        self.assertEqual((a["range"]["startColumnIndex"], a["range"]["endRowIndex"]), (17, 900))
        self.assertNotIn("left", a)                       # the block's right edge stays
        self.assertEqual((b["range"]["endRowIndex"], "left" in b), (2, True))


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
