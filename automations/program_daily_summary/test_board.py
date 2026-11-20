"""python -m unittest automations.program_daily_summary.test_board"""
import datetime as dt
import unittest

from automations.program_daily_summary import board as B
from automations.program_daily_summary import layout as L

D = dt.date


class Week(unittest.TestCase):
    def test_monday_still_fills_the_closing_week(self):
        self.assertEqual(B.target_monday(D(2026, 11, 23)), D(2026, 11, 16))
        self.assertEqual(B.target_monday(D(2026, 11, 24)), D(2026, 11, 23))

    def test_c3_serial_to_date(self):
        self.assertEqual(B.parse_we(46348), D(2026, 11, 22))
        self.assertIsNone(B.parse_we(""))


class Cells(unittest.TestCase):
    def test_unreported_and_future_days_blank_not_zero(self):
        data = {"Fios": {D(2026, 11, 16): 522, D(2026, 11, 18): 541,
                         D(2026, 11, 20): 0}}
        got = B.day_cells(D(2026, 11, 16), data, today=D(2026, 11, 20))
        self.assertEqual(got, {"Fios": [522, "", 541, "", "", "", ""]})

    def test_history_rows_all_first_then_each_campaign(self):
        cells = {c: [1, 2, 3, 4, 5, 6, 7] for c in L.CAMPAIGNS}
        rows = B.history_rows(D(2026, 11, 16), cells)
        self.assertEqual([r[1] for r in rows], [L.ALL] + L.CAMPAIGNS)
        self.assertEqual(rows[0][0], "11/22/2026")
        self.assertEqual(rows[0][2:9], [5, 10, 15, 20, 25, 30, 35])
        self.assertEqual(rows[0][9], 140)
        self.assertEqual(rows[1][9], 28)

    def test_no_all_row_when_a_campaign_is_missing(self):
        cells = {"Fios": [1] * 7}
        rows = B.history_rows(D(2026, 11, 16), cells)
        self.assertNotIn(L.ALL, [r[1] for r in rows])
        self.assertEqual([r[1] for r in rows], ["Fios"])
        self.assertEqual(rows[0][9], 7)


class Locate(unittest.TestCase):
    def test_rows_by_label(self):
        col = ["", "COUNTRY", L.WE_LABEL, L.PS_BAR, "Product Type",
               *L.CAMPAIGNS, "Grand Total", "", "x", "All Campaigns: Mon-Sun",
               "Sales - This Week"]
        r = B.locate(col)
        self.assertEqual((r["we"], r["bar"]), (3, 4))
        self.assertEqual(r["campaigns"]["ATT Fiber"], 6)
        self.assertEqual(r["total"], 11)

    def test_missing_label_is_loud(self):
        with self.assertRaises(RuntimeError):
            B.locate([L.PS_BAR, "ATT Fiber"])


if __name__ == "__main__":
    unittest.main()
