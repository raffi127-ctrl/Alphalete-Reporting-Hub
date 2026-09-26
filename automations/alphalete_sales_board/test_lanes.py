import unittest

from automations.alphalete_sales_board import lanes as L

F = ("=iferror(FILTER('Sales Board WE 9.27'!C4:C87, "
     "'Sales Board WE 9.27'!D4:D87<4,'Sales Board WE 9.27'!C4:C87<>0),\"\")")


def _grid(cur, last, excl=False):
    vals = [["Current Week", "", "", "Last week", "", ""],
            ["Super", "Fast", "", "Super", "Fast", ""],
            ["x", "y", "", "x", "y", ""]]
    if excl:        # a tab that already carries the terminated list (col G)
        vals[1].append("Terminated (auto)")
        cur, last = (L.with_exclusion(f, "G", 3) for f in (cur, last))
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
        forms, vals = _grid(cur, last, excl=True)
        t = {"current": ("Sales Board WE 9.27", 87), "last": ("Sales Board WE 9.20", 88)}
        self.assertEqual(L.plan(forms, vals, t), [])

    def test_monday_roll_moves_both_blocks(self):
        cur = "=FILTER('Sales Board WE 9.27'!C4:C87, 'Sales Board WE 9.27'!D4:D87>=10)"
        last = "=FILTER('Sales Board WE 9.20'!C4:C88, 'Sales Board WE 9.20'!D4:D88>=10)"
        forms, vals = _grid(cur, last, excl=True)
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


class TerminatedTest(unittest.TestCase):
    def test_exclusion_added_once_and_repointed(self):
        once = L.with_exclusion(F, "M", 3)
        self.assertIn("ISNA(MATCH('Sales Board WE 9.27'!C4:C87, $M$3:$M, 0))),\"\")", once)
        self.assertEqual(L.with_exclusion(once, "M", 3), once)
        out = L.repoint(once, "Sales Board WE 10.4", 90)
        self.assertIn("MATCH('Sales Board WE 10.4'!C4:C90, $M$3:$M", out)
        self.assertIn("D4:D90<4", out)

    def test_excluded_names_keep_exact_spelling(self):
        col_c = ["", "", "WE", "Ana Griffin", "Claudia Lopez ", "Bailey Soda",
                 "Zed", "TOTALS", "Claudia Lopez "]
        got = L.excluded_names(col_c, 7, {"claudia lopez", "bailey soda"})
        self.assertEqual(got, ["Claudia Lopez ", "Bailey Soda"])

    def test_plan_writes_header_list_and_formulas(self):
        cur = "=iferror(FILTER('Sales Board WE 9.27'!C4:C87, 'Sales Board WE 9.27'!D4:D87>=10),\"\")"
        forms, vals = _grid(cur, cur.replace("9.27", "9.20"))
        t = {"current": ("Sales Board WE 9.27", 87), "last": ("Sales Board WE 9.20", 87)}
        ups = {u["range"]: u["values"] for u in L.plan(forms, vals, t, ["Ana "])}
        self.assertEqual(ups["G2"], [["Terminated (auto)"]])
        self.assertEqual(ups["G3:G3"], [["Ana "]])
        self.assertIn("$G$3:$G", ups["A3"][0][0])

    def test_list_shrinks_by_blanking(self):
        cur = "=iferror(FILTER('Sales Board WE 9.27'!C4:C87, 'Sales Board WE 9.27'!D4:D87>=10, ISNA(MATCH('Sales Board WE 9.27'!C4:C87, $G$3:$G, 0))),\"\")"
        vals = [["Current Week", "", "", "Last week", "", "", ""],
                ["Super", "Fast", "", "Super", "Fast", "", "Terminated (auto)"],
                ["x", "y", "", "x", "y", "", "Ana"],
                ["", "", "", "", "", "", "Bo"]]
        last = cur.replace("9.27", "9.20")
        forms = [vals[0], vals[1], [cur, cur, "", last, last, ""]]
        t = {"current": ("Sales Board WE 9.27", 87), "last": ("Sales Board WE 9.20", 87)}
        ups = L.plan(forms, vals, t, ["Bo"])
        self.assertEqual(ups, [{"range": "G3:G4", "values": [["Bo"], [""]],
                                "old": "2 name(s)"}])

    def test_paused_touches_only_formulas_never_the_list(self):
        # Maud 9/26: terminated part off -> only tab + end row move; the
        # existing list and ISNA condition are left exactly as they are.
        forms, vals = _grid(F, F, excl=True)
        vals.append(["", "", "", "", "", "", "Ana"])
        t = {"current": ("Sales Board WE 10.4", 99), "last": ("Sales Board WE 9.27", 88)}
        ups = L.plan(forms, vals, t, ["Bo"], exclude_terminated=False)
        self.assertEqual(sorted(u["range"] for u in ups), ["A3", "B3", "D3", "E3"])
        for u in ups:
            self.assertEqual(u["values"][0][0].count("ISNA(MATCH("), 1)

    def test_paused_does_not_add_the_condition(self):
        forms, vals = _grid(F, F)
        t = {"current": ("Sales Board WE 10.4", 99), "last": ("Sales Board WE 9.27", 88)}
        ups = L.plan(forms, vals, t, ["Bo"], exclude_terminated=False)
        self.assertTrue(ups)
        for u in ups:
            self.assertNotIn("ISNA", u["values"][0][0])


if __name__ == "__main__":
    unittest.main()
