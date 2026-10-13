"""python -m unittest automations.sheet_format_audit.test_audit"""
import unittest

from automations.sheet_format_audit import audit as A

SID = 7

HDR1 = ["October BOB Call / Stats"]
HDR2 = ["Team Name", "Leader Name", "2nd rds conducted", "Job offered",
        "Job Offered %", "BOB # / Accepted", "BOB %", "New Start Scheduled",
        "New starts showed", "NS Showed %"]


def _grid(rows):
    """rows: [(name, ns_formula)] -> shown, formulas (A-J, row 3 on)."""
    shown = [HDR1, HDR2]
    formulas = [[None], [None] * 10]
    for i, (name, ns_f) in enumerate(rows, start=3):
        shown.append(["T", name, "4", "2", "50%", "1", "50%", "2", "1", "50%"])
        formulas.append([None, None, None, None, f"=iferror(D{i}/C{i},0)", None,
                         f"=iferror(F{i}/D{i},0)", None, None,
                         ns_f or f"=iferror(I{i}/H{i},0)"])
    t = len(shown) + 1
    shown.append(["", "TOTALS", "8", "4", "50%", "2", "50%", "4", "2", "50%"])
    formulas.append([None, None, f"=SUM(C3:C{t - 1})", f"=SUM(D3:D{t - 1})",
                     f"=iferror(D{t}/C{t},0)", f"=SUM(F3:F{t - 1})",
                     f"=iferror(F{t}/D{t},0)", f"=SUM(H3:H{t - 1})",
                     f"=SUM(I3:I{t - 1})", f"=iferror(I{t}/H{t},0)"])
    return shown, formulas


def _all_rules():
    rules = []
    for m in A.METRICS:
        col = {"offered_pct": 5, "bob_pct": 7, "ns_pct": 10}[m.key]
        rules += A.color_rules(SID, m, col, 3, 66)
    return rules


class Colors(unittest.TestCase):
    def test_no_rules_is_flagged_and_fix_adds_four_per_column(self):
        shown, formulas = _grid([("Andrew", None), ("Bill", None)])
        f = [x for x in A.audit(shown, formulas, [], SID) if x.kind == "colors"]
        self.assertEqual(len(f), 3)
        self.assertTrue(all(len(x.fix["add_rules"]) == 4 for x in f))

    def test_correct_rules_are_clean(self):
        shown, formulas = _grid([("Andrew", None), ("Bill", None)])
        self.assertEqual(A.audit(shown, formulas, _all_rules(), SID), [])

    def test_83_and_80_percent_bob_is_green(self):
        r = _all_rules()
        self.assertEqual(A.shown_color(r, 8, 6, 0.83, SID), "green")
        self.assertEqual(A.shown_color(r, 12, 6, 0.80, SID), "green")
        self.assertEqual(A.shown_color(r, 12, 6, 0.0, SID), "white")
        self.assertEqual(A.shown_color(r, 12, 6, 0.43, SID), "red")

    def test_first_matching_rule_wins(self):
        # NS column sitting under a BOB rule first (the old months): 65% is
        # yellow there, but the legend says green.
        bob = next(m for m in A.METRICS if m.key == "bob_pct")
        wrong = A.color_rules(SID, bob, 10, 3, 66) + _all_rules()
        shown, formulas = _grid([("Andrew", None)])
        f = [x for x in A.audit(shown, formulas, wrong, SID) if x.kind == "colors"]
        self.assertEqual([x.where for x in f], ["J3:J3"])


class Formulas(unittest.TestCase):
    def test_ns_divided_by_bob_pct_is_fixed(self):
        shown, formulas = _grid([("Andrew", "=iferror(I3/G3,0)"), ("Bill", None)])
        f = [x for x in A.audit(shown, formulas, _all_rules(), SID) if x.kind == "formula"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].fix["formulas"], {"J3": "=iferror(I3/H3,0)"})

    def test_typed_number_is_flagged_not_fixed(self):
        shown, formulas = _grid([("Andrew", None)])
        formulas[2][9] = None
        f = [x for x in A.audit(shown, formulas, _all_rules(), SID) if x.kind == "formula"]
        self.assertEqual(len(f), 1)
        self.assertIsNone(f[0].fix)

    def test_totals_that_skip_people(self):
        shown, formulas = _grid([("Andrew", None), ("Bill", None), ("Sydney", None)])
        formulas[5][2] = "=SUM(C4:C5)"
        f = [x for x in A.audit(shown, formulas, _all_rules(), SID) if x.kind == "totals"]
        self.assertEqual(f[0].fix["formulas"], {"C6": "=SUM(C3:C5)"})


class OnlyCurrentMonth(unittest.TestCase):
    def test_older_block_ignored_unless_all_months(self):
        shown, formulas = _grid([("Andrew", None)])
        # second block, September, no rules at all, starting at col L
        shown[0] = HDR1 + [""] * 11 + ["September BOB Call / Stats"]
        shown[1] = HDR2 + ["", ""] + HDR2[1:] + ["x"]
        for r in range(2, len(shown)):
            shown[r] = shown[r] + ["", ""] + shown[r][1:]
            formulas[r] = formulas[r] + [None, None] + [None] * 9
        self.assertEqual(A.audit(shown, formulas, _all_rules(), SID), [])
        self.assertTrue(A.audit(shown, formulas, _all_rules(), SID, all_months=True))


if __name__ == "__main__":
    unittest.main()
