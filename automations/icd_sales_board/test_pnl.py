"""The P&L reader: absent vs zero, and never printing a broken formula."""
import datetime as dt
import unittest

from automations.icd_sales_board import pnl as PL

W1, W2 = dt.date(2026, 9, 20), dt.date(2026, 9, 13)
WEEKS = [W1, W2]


def data(rows):
    return {"weeks": WEEKS,
            "metrics": {n: {"goal": g, "by_week": by} for n, g, by in rows}}


class UsableTests(unittest.TestCase):
    def test_a_broken_formula_is_not_a_value(self):
        for bad in ("#REF!", "#N/A", "#DIV/0!", "#value!"):
            self.assertFalse(PL.usable(bad), bad)

    def test_a_real_figure_is(self):
        self.assertTrue(PL.usable("$3,070.51"))
        self.assertTrue(PL.usable("-$13,928.76"))
        self.assertTrue(PL.usable("0"))       # a real zero IS a value

    def test_blank_is_not(self):
        self.assertFalse(PL.usable(""))
        self.assertFalse(PL.usable(None))


class RowTests(unittest.TestCase):
    def test_the_block_comes_back_in_its_own_order(self):
        d = data([("Operating %", "", {W1: "47%", W2: "50%"}),
                  ("Direct Deposit", "", {W1: "$1", W2: "$2"}),
                  ("Profit/Loss", "", {W1: "$3", W2: "$4"})])
        got = [r["Metric"] for r in PL.rows_for(d, WEEKS)]
        self.assertEqual(got, ["Direct Deposit", "Profit/Loss", "Operating %"])

    def test_a_row_of_broken_formulas_is_dropped_entirely(self):
        # Raf's whole B2B and JE block reads #REF! today.
        d = data([("B2B PNL", "", {W1: "#REF!", W2: "#REF!"}),
                  ("Profit/Loss", "", {W1: "$3", W2: ""})])
        self.assertEqual([r["Metric"] for r in PL.rows_for(d, WEEKS)],
                         ["Profit/Loss"])

    def test_one_broken_week_blanks_that_cell_and_keeps_the_row(self):
        d = data([("Profit/Loss", "", {W1: "#REF!", W2: "$4"})])
        row = PL.rows_for(d, WEEKS)[0]
        self.assertEqual(row[f"{W1:%m/%d}"], "")
        self.assertEqual(row[f"{W2:%m/%d}"], "$4")

    def test_an_office_with_no_books_has_no_rows(self):
        d = data([("1ST SHOWED", "", {W1: "49", W2: "71"})])
        self.assertEqual(PL.rows_for(d, WEEKS), [])
        self.assertFalse(PL.has_pnl(d, WEEKS))

    def test_a_per_program_vocabulary_is_found_too(self):
        # Raf's tab splits by program instead of using the nine-row block.
        d = data([("Fiber PNL", "$41,400", {W1: "$900", W2: ""}),
                  ("JE Profit Margin %", "25%", {W1: "12%", W2: ""})])
        self.assertEqual(len(PL.rows_for(d, WEEKS)), 2)


class HeadlineTests(unittest.TestCase):
    def test_the_headline_skips_broken_figures(self):
        d = data([("Profit/Loss", "", {W1: "#REF!", W2: "$4"}),
                  ("Operating %", "", {W1: "47%", W2: ""})])
        self.assertEqual(PL.headline(d, W1), [("Operating %", "47%")])

    def test_nothing_usable_is_an_empty_headline_not_a_zero(self):
        d = data([("Profit/Loss", "", {W1: "#REF!", W2: "#REF!"})])
        self.assertEqual(PL.headline(d, W1), [])


if __name__ == "__main__":
    unittest.main()
