import unittest

from automations.alphalete_sales_board import lanes as L

F = ("=iferror(FILTER('Sales Board WE 9.27'!C4:C87, "
     "'Sales Board WE 9.27'!D4:D87<4,'Sales Board WE 9.27'!C4:C87<>0),\"\")")


def _grid(cur, last):
    vals = [["Current Week", "", "", "Last week", "", ""],
            ["Super", "Fast", "", "Super", "Fast", ""],
            ["x", "y", "", "x", "y", ""]]
    forms = [vals[0], vals[1], [cur, cur, "", last, last, ""]]
    return forms, vals


class RepointTest(unittest.TestCase):
    def test_swaps_tab_and_end_row_keeps_conditions(self):
        out = L.repoint(F, "Sales Board WE 10.4", 90)
        self.assertEqual(out.count("'Sales Board WE 10.4'!"), 3)
        self.assertIn("C4:C90", out)
        self.assertIn("D4:D90<4", out)
        self.assertIn("<>0", out)
        self.assertNotIn("9.27", out)

    def test_refuses_formula_without_board_ref(self):
        with self.assertRaises(ValueError):
            L.repoint("=SUM(A1:A3)", "Sales Board WE 10.4", 90)


class PlanTest(unittest.TestCase):
    def test_nothing_to_do_when_already_right(self):
        cur = "=FILTER('Sales Board WE 9.27'!C4:C87, 'Sales Board WE 9.27'!D4:D87>=10)"
        last = "=FILTER('Sales Board WE 9.20'!C4:C88, 'Sales Board WE 9.20'!D4:D88>=10)"
        forms, vals = _grid(cur, last)
        t = {"current": ("Sales Board WE 9.27", 87), "last": ("Sales Board WE 9.20", 88)}
        self.assertEqual(L.plan(forms, vals, t), [])

    def test_monday_roll_moves_both_blocks(self):
        cur = "=FILTER('Sales Board WE 9.27'!C4:C87, 'Sales Board WE 9.27'!D4:D87>=10)"
        last = "=FILTER('Sales Board WE 9.20'!C4:C88, 'Sales Board WE 9.20'!D4:D88>=10)"
        forms, vals = _grid(cur, last)
        t = {"current": ("Sales Board WE 10.4", 80), "last": ("Sales Board WE 9.27", 87)}
        ups = {u["range"]: u["values"][0][0] for u in L.plan(forms, vals, t)}
        self.assertEqual(sorted(ups), ["A3", "B3", "D3", "E3"])
        self.assertIn("'Sales Board WE 10.4'!C4:C80", ups["A3"])
        self.assertIn("'Sales Board WE 9.27'!C4:C87", ups["D3"])

    def test_blank_formula_cell_refuses(self):
        forms, vals = _grid("", "")
        t = {"current": ("a", 1), "last": ("b", 1)}
        with self.assertRaises(RuntimeError):
            L.plan(forms, vals, t)

    def test_totals_row(self):
        self.assertEqual(L.totals_row(["", "#", "WE", "Ana", "TOTALS"]), 5)
        self.assertIsNone(L.totals_row(["a", "b"]))


if __name__ == "__main__":
    unittest.main()
