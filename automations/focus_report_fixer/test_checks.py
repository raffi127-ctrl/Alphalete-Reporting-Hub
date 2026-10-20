"""python -m unittest automations.focus_report_fixer.test_checks"""
import datetime as dt
import unittest

from automations.focus_report_fixer import checks as FC

TODAY = dt.date(2026, 10, 19)
SUNDAYS = [dt.date(2026, 9, 6) + dt.timedelta(days=7 * i) for i in range(10)]


def grid(rows, n=10, start=SUNDAYS[0]):
    """rows = [(label, fn(col_letter) -> cell)], row 1 = dates."""
    from automations.sales_board_fixer.checks import col_letter
    weeks = [(start + dt.timedelta(days=7 * i)) for i in range(n)]
    vals = [["Goal", "WE SUNDAY"] + ["%d/%d/%d" % (d.month, d.day, d.year % 100) for d in weeks]]
    forms = [list(vals[0])]
    for label, fn in rows:
        cells = [fn(col_letter(c)) for c in range(3, 3 + n)]
        forms.append(["", label] + cells)
        vals.append(["", label] + ["#REF!" if "#REF!" in str(x) else
                                   ("0" if str(x).startswith("=") else x) for x in cells])
    return vals, forms


TPL = grid([("Active Headcount on Tableau", lambda c: ""),
            ("New Internets", lambda c: ""),
            ("AVG New INT Per Active Headcount", lambda c: "=IFERROR(%s3/%s2,0)" % (c, c))])


class Focus(unittest.TestCase):
    def test_ref_with_no_working_formula_comes_from_the_template(self):
        # the tab keeps an extra row on top: rows are matched by LABEL
        v, f = grid([("Notes", lambda c: ""),
                     ("Active Headcount on Tableau", lambda c: "5"),
                     ("New Internets", lambda c: "2"),
                     ("AVG New INT Per Active Headcount",
                      lambda c: "=IFERROR(#REF!/%s3,0)" % c)])
        found = [x for x in FC.check_tab("t", v, f, *TPL, TODAY) if x.kind == "fr_ref_error"]
        self.assertEqual(len(found), 10)
        self.assertEqual(found[0].value, "=IFERROR(C4/C3,0)")

    def test_ref_takes_the_rows_own_formula_first(self):
        v, f = grid([("Active Headcount on Tableau", lambda c: "5"),
                     ("New Internets", lambda c: "2"),
                     ("AVG New INT Per Active Headcount",
                      lambda c: "=IFERROR(#REF!/E2,0)" if c == "E" else "=IFERROR(%s3/%s2,0)" % (c, c))])
        x = [y for y in FC.check_tab("t", v, f, *TPL, TODAY) if y.kind == "fr_ref_error"][0]
        self.assertEqual((x.where, x.value), ("E4", "=IFERROR(E3/E2,0)"))

    def test_ref_repair_never_rewrites_the_rest(self):
        v, f = grid([("Active Headcount on Tableau", lambda c: "5"),
                     ("New Internets", lambda c: "2"),
                     ("AVG New INT Per Active Headcount",
                      lambda c: "=IFERROR(#REF!/E1,0)" if c == "E" else "=IFERROR(%s3/%s2,0)" % (c, c))])
        x = [y for y in FC.check_tab("t", v, f, *TPL, TODAY) if y.kind == "fr_ref_error"][0]
        self.assertIsNone(x.value)
        self.assertTrue(FC.fills_refs("=#REF!+#REF!", "=AB35+AB65"))
        self.assertFalse(FC.fills_refs("=SUM(AD33/2)+(#REF!)", "=IFERROR(AD33/AD29,0)"))

    def test_only_holes_get_a_formula_back(self):
        v, f = grid([("Active Headcount on Tableau", lambda c: "5"),
                     ("New Internets", lambda c: "2"),
                     ("Cost per NS", lambda c: "" if c in ("E", "L") else "=%s3/%s2" % (c, c))])
        found = [x for x in FC.check_tab("t", v, f, *TPL, TODAY) if x.kind == "fr_blank"]
        self.assertEqual([x.where for x in found], ["E4"])      # L4 is the end of the run

    def test_rows_reports_fill_are_never_filled(self):
        v, f = grid([("Active Headcount on Tableau", lambda c: "5"),
                     ("New Internets", lambda c: "2"),
                     ("AVG New INT Per Active Headcount",
                      lambda c: "" if c == "E" else "=IFERROR(%s3/%s2,0)" % (c, c))])
        filled = FC.rows_filled_by_reports()
        self.assertFalse([x for x in FC.check_tab("t", v, f, *TPL, TODAY, filled)
                          if x.kind == "fr_blank"])

    def test_typed_numbers_are_not_findings(self):
        v, f = grid([("Active Headcount on Tableau", lambda c: "5"),
                     ("New Internets", lambda c: "2"),
                     ("AVG New INT Per Active Headcount",
                      lambda c: "0.4" if c < "F" else "=IFERROR(%s3/%s2,0)" % (c, c))])
        self.assertEqual(FC.check_tab("t", v, f, *TPL, TODAY), [])

    def test_odd_formula_is_one_line_and_report_only(self):
        v, f = grid([("Job Offered", lambda c: "2"), ("BOB", lambda c: "1"),
                     ("2ND SHOWED", lambda c: "4"),
                     ("Job Offered Retention",
                      lambda c: "=iferror(%s2/%s4,0)" % (c, c) if c > "D"
                      else "=iferror(%s3/%s2,0)" % (c, c))])
        odd = [x for x in FC.check_tab("t", v, f, *TPL, TODAY) if x.kind == "fr_odd_formula"]
        self.assertEqual(len(odd), 1)
        self.assertIn("2 week(s)", odd[0].detail)
        self.assertFalse(odd[0].fixable)

    def test_renamed_template_row_is_reported(self):
        v, f = grid([("Active Headcount on Tableau", lambda c: "5"),
                     ("New Internets", lambda c: "2"),
                     ("AVG New INT / Head", lambda c: "=IFERROR(%s3/%s2,0)" % (c, c))])
        miss = [x for x in FC.check_tab("t", v, f, *TPL, TODAY) if x.kind == "fr_label_missing"]
        self.assertEqual(len(miss), 1)

    def test_dates_off_are_one_line(self):
        v, f = grid([("New Internets", lambda c: "2")], start=dt.date(2026, 9, 5))  # Saturdays
        d = FC.check_dates("t", v)
        self.assertEqual(len(d), 1)
        self.assertIn("10 week headers off", d[0].detail)


if __name__ == "__main__":
    unittest.main()
