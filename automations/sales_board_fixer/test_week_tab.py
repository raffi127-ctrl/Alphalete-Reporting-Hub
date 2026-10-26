"""python -m unittest automations.sales_board_fixer.test_week_tab"""
import datetime as dt
import unittest

from automations.sales_board_fixer import week_tab as W

# Omar's layout, cut down: names in B, the three week-total banners, then MON
# (Apps formula, Int / Cx typed, Roll Call typed) and the trainer column.
BANNER = ["x", "KALKAN", "RUNNING WEEK TOTALS", "", "LAST WEEK'S TOTALS", "",
          "PRIOR WEEK'S TOTALS", "", "MON", "Monday", "", "", "SUN", "Sunday", "", "", "Trainer"]
DATES = [""] * 8 + [19, "", "", "", "=I2+6", "", "", "", ""]
SUB = ["#", "WE9/7-9/13", "APPS", "INT", "APPS", "INT", "Apps", "INT",
       "Apps", "Int", "Cx", "Roll Call", "Apps", "Int", "Cx", "Roll Call", "REP"]


def board():
    rep = [1, "JON", "=SUM(I4,M4)", "=SUM(J4,N4)", 3, 1, 0, 0,
           "=J4+K4", 2, 1, "Here", "=N4+O4", 4, "", "Late", "Omar"]
    totals = ["", "TOTALS", "=SUM(C4:C4)", "=SUM(D4:D4)", 3, 1, 0, 0,
              "=SUM(I4:I4)", "=SUM(J4:J4)", "=SUM(K4:K4)", "", "=SUM(M4:M4)", "", "", "", ""]
    formulas = [BANNER, DATES, SUB, rep, totals]
    raw = [BANNER, DATES, SUB,
           [1, "JON", 9, 6, 3, 1, 0, 0, 3, 2, 1, "Here", 6, 4, "", "Late", "Omar"],
           ["", "TOTALS", 9, 6, 3, 1, 0, 0, 3, 2, 1, "", 6, "", "", "", ""]]
    values = [[str(x) for x in r] for r in raw]
    return values, formulas, raw


class PlanTest(unittest.TestCase):
    def setUp(self):
        v, f, r = board()
        self.cells = W.plan(v, f, r, dt.date(2026, 11, 2))

    def test_typed_day_cells_go_blank_formulas_stay(self):
        for a1 in ("J4", "K4", "L4", "N4", "P4"):
            self.assertEqual(self.cells.get(a1), "", a1)
        for a1 in ("I4", "M4", "C4", "O4"):      # Apps formulas, an empty Cx
            self.assertNotIn(a1, self.cells, a1)

    def test_trainer_column_is_kept(self):
        self.assertNotIn("Q4", self.cells)

    def test_last_week_gets_running_and_prior_gets_last(self):
        self.assertEqual(self.cells["E4"], 9)    # last week Apps <- running Apps
        self.assertEqual(self.cells["F4"], 6)
        self.assertEqual(self.cells["G4"], 3)    # prior week Apps <- last week Apps
        self.assertEqual(self.cells["H4"], 1)
        self.assertEqual(self.cells["E5"], 9)    # the TOTALS row too

    def test_monday_date_and_week_label_move(self):
        self.assertEqual(self.cells["I2"], 2)
        self.assertEqual(self.cells["B3"], "WE11/2-11/8")
        self.assertNotIn("M2", self.cells)       # Sunday's date is a formula


class FieldStatusTest(unittest.TestCase):
    def test_one_week_further(self):
        self.assertEqual(W.next_week_status("1st Wk"), "2nd Wk")
        self.assertEqual(W.next_week_status("3rd Wk"), "4th Wk")
        self.assertEqual(W.next_week_status("4th Wk"), "5th Wk+")
        self.assertEqual(W.next_week_status("2nd Week"), "3rd Week")

    def test_last_bucket_and_others_stay(self):
        for s in ("5th Wk+", "RT", "Roadtrip", "", "Classroom"):
            self.assertIsNone(W.next_week_status(s), s)

    def test_plan_moves_the_column(self):
        v, f, r = board()
        for g in (v, f, r):
            g[0] = g[0] + ["Field Status"]
            g[2] = g[2] + [""]
            g[3] = g[3] + ["1st Wk"]
            g[4] = g[4] + [""]
        self.assertEqual(W.plan(v, f, r, dt.date(2026, 11, 2))["R4"], "2nd Wk")


class WeekTest(unittest.TestCase):
    def sheets(self, *titles):
        return [{"properties": {"title": t, "sheetId": i, "index": i}} for i, t in enumerate(titles)]

    def test_newest_week_by_date_not_by_position(self):
        today = dt.date(2026, 11, 2)
        d, p = W.newest_week(self.sheets("10/25", "Stations", "11/01", "Lanes"), today)
        self.assertEqual((d, p["title"]), (dt.date(2026, 11, 1), "11/01"))

    def test_december_tab_read_in_january_is_last_year(self):
        self.assertEqual(W.tab_date("12/27", dt.date(2027, 1, 4)), dt.date(2026, 12, 27))

    def test_history_line_is_the_closed_weeks_totals(self):
        v, f, r = board()
        for g in (v, r):
            g += [["", "Reps in the Field", 7], ["", "% of Reps on the Board", 0.5]]
        self.assertEqual(W.history_row(v, r, dt.date(2026, 11, 1)),
                         ["WE 10/26 - 11/1", 9, 6, 3, 1, 0, 0, 7, 0.5])

    def test_name_pads_like_omars(self):
        self.assertEqual(W.tab_name(dt.date(2026, 11, 1)), "11/01")


if __name__ == "__main__":
    unittest.main()
