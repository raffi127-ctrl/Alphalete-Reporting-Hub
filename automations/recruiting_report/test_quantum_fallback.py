import datetime as dt
import unittest

from automations.recruiting_report import quantum_fallback as Q

WE = dt.date(2026, 9, 27)

SALES = [
    ["ICD Owner [Office] (Nest)", "10/4/2026", "9/27/2026", "9/20/2026"],
    ["", "", "", "1"],
    ["NIGEL MARSHALL [vp executives, inc.]", "", "203", "207"],
    ["ANGEL PADILLA [azul connections inc]", "", "64", "174"],
]
HC = [
    ["ICD Owner Name", "ICD Office Name (+/- State)", "Average", "9/27/2026", "9/20/2026"],
    ["Nigel Marshall", "VP Executives, Inc.", "42.75", "42", "41"],
    ["Angel Padilla", "Azul Connections Inc", "26", "31", "25"],
]
CFG = Q.TABS["Nigel Marshall"]


class QuantumFallbackTest(unittest.TestCase):
    def test_sales_for_week(self):
        self.assertEqual(Q.quantum_sales(SALES, CFG["sales_key"], WE), 203)
        self.assertEqual(Q.quantum_sales(SALES, CFG["sales_key"], dt.date(2026, 9, 20)), 207)

    def test_sales_blank_or_missing_week_is_none(self):
        self.assertIsNone(Q.quantum_sales(SALES, CFG["sales_key"], dt.date(2026, 10, 4)))
        self.assertIsNone(Q.quantum_sales(SALES, CFG["sales_key"], dt.date(2026, 8, 30)))

    def test_headcount_for_week(self):
        self.assertEqual(Q.quantum_headcount(HC, CFG["owner"], CFG["office"], WE), 42)

    def test_unknown_icd_is_none(self):
        self.assertIsNone(Q.quantum_sales(SALES, "nobody [x]", WE))
        self.assertIsNone(Q.quantum_headcount(HC, "nobody", "x", WE))

    def test_att_fiber_wins(self):
        self.assertEqual(Q.decide("12", ""), "att")

    def test_no_att_fiber_uses_quantum(self):
        for v in ("", "0", "0.0"):
            self.assertEqual(Q.decide(v, ""), "quantum")

    def test_our_own_quantum_value_is_not_att(self):
        self.assertEqual(Q.decide("203", Q.NOTE), "quantum")


class RecruitingCheckTest(unittest.TestCase):
    ROWS = {"pull": 2, "first_booked": 3, "total_applies": 4}
    GRID = [["", "WE SUNDAY", "9/20/26", "9/27/26"],
            ["", "Sent To Call List", "636", ""],
            ["", "1ST BOOKED", "0", ""],
            ["", "Total Applies", "861", "0"]]

    def test_filled_week(self):
        self.assertTrue(Q.recruiting_filled(self.GRID, 3, self.ROWS))

    def test_empty_week_even_if_formula_rows_show_zero(self):
        self.assertFalse(Q.recruiting_filled(self.GRID, 4, self.ROWS))

    def test_no_metric_rows_is_not_filled(self):
        self.assertFalse(Q.recruiting_filled(self.GRID, 3, {}))

    def test_verdict(self):
        self.assertEqual(Q._verdict([]), 0)
        self.assertEqual(Q._verdict(["x"]), 1)


if __name__ == "__main__":
    unittest.main()
