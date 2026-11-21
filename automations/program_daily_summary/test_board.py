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


class _FakeData:
    def __init__(self, grid):
        self.grid, self.inserted = grid, []

    def get(self, *_a, **_k):
        return self.grid

    def insert_rows(self, rows, row, **_k):
        self.inserted.append((row, rows))


class Backfill(unittest.TestCase):
    MON = D(2026, 11, 9)

    def _data(self, camps):
        return {c: {self.MON + dt.timedelta(days=k): 10 for k in range(7)}
                for c in camps}

    def test_adds_only_missing_campaigns_and_the_all_row(self):
        we = 46341                                   # 11/15/2026 serial
        stored = [[we, c] + [10] * 7 + [70] for c in ("Frontier", "Fios")]
        fake = _FakeData(stored)
        B.backfill_week(self.MON, self._data(L.CAMPAIGNS), data_ws=fake,
                        logfn=lambda *_: None)
        (row, rows), = fake.inserted
        names = [r[2] for r in rows]                 # col A pad, then WE, camp
        self.assertEqual(names, [L.ALL, "ATT Fiber", "ATT NDS", "B2B"])
        self.assertEqual(rows[0][-1], 350)           # 5 campaigns x 70

    def test_partial_week_gets_no_all_row(self):
        fake = _FakeData([])
        B.backfill_week(self.MON, self._data(["ATT Fiber"]), data_ws=fake,
                        logfn=lambda *_: None)
        (_, rows), = fake.inserted
        self.assertEqual([r[2] for r in rows], ["ATT Fiber"])

    def test_nothing_new_inserts_nothing(self):
        fake = _FakeData([[46341, "ATT Fiber"] + [10] * 7 + [70]])
        B.backfill_week(self.MON, self._data(["ATT Fiber"]), data_ws=fake,
                        logfn=lambda *_: None)
        self.assertEqual(fake.inserted, [])


class History(unittest.TestCase):
    def test_span_reaches_oldest_week(self):
        shown = D(2026, 11, 22)
        self.assertEqual(B.history_span([D(2026, 11, 15)], shown), 1)
        self.assertEqual(B.history_span([D(2026, 11, 15), D(2026, 9, 27), None],
                                        shown), 8)
        self.assertEqual(B.history_span([], shown), 0)

    def test_column_letters_past_z(self):
        self.assertEqual([L._col(i) for i in (2, 9, 10, 25, 26, 27)],
                         ["C", "J", "K", "Z", "AA", "AB"])

    def test_formulas_step_back_a_week_per_column(self):
        f = L.history_formulas(10)                       # K = 9th week back
        self.assertEqual(f[f"K{L.R_HIST_HDR}"], "=$C$3-63")
        self.assertIn(f"K${L.R_HIST_HDR}", f[f"K{L.R_HIST_FIRST}"])


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
