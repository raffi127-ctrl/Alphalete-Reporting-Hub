import unittest

from automations.pnl_fixer import checks as P


def pnl(reps, weeks=6, spare=2):
    """The template's shape: A-D rep columns, then per week Brought In / Got
    Paid / Profit/Loss; a blank row, then the totals (label in Got Paid)."""
    row1 = ["PNL 2026", "", "REPS", "", "46026"]
    row2 = ["Current", "Leader", "First Name", "Last Name"]
    for w in range(weeks):
        if w:
            row1 += ["", "", "=%s1+7" % P.K.col_letter(5 + 3 * (w - 1))]
        row2 += ["Brought In", "Got Paid", "Profit/Loss"]
    row1 += [""] * 2
    f = [row1, row2]
    for i, (first, last, amounts, gaps) in enumerate(reps + [("", "", {}, ())] * spare):
        r = 3 + i
        row = ["", "", first, last]
        for w in range(weeks):
            bi, gp = amounts.get(w, ("", ""))
            e, g = P.K.col_letter(5 + 3 * w), P.K.col_letter(6 + 3 * w)
            row += [bi, gp, "" if w in gaps else "=SUM(%s%d)-(%s%d*1.12)" % (e, r, g, r)]
        f.append(row)
    last_rep = len(f)
    f.append([""] * len(row2))
    for lab, tmpl in (("Total Loss", '=SUMIF({p}3:{p}%d,"<0")' % last_rep),
                      ("Total Gross Profit", '=SUMIF({p}3:{p}%d,">0")' % last_rep),
                      ("Payroll", "=SUM({g}3:{g}%d)" % last_rep),
                      ("Expenses", "500")):
        row = ["", "", "", ""]
        for w in range(weeks):
            p, g = P.K.col_letter(7 + 3 * w), P.K.col_letter(6 + 3 * w)
            row += ["", lab, tmpl.format(p=p, g=g)]
        f.append(row)
    return f


class Reps(unittest.TestCase):
    def test_missing_formula_in_a_week_with_money_is_put_back(self):
        f = pnl([("Nick", "", {1: ("411", "500")}, (1, 2))] + [("Rep%d" % i, "", {}, ()) for i in range(6)])
        found = P.check_reps(f, f)
        self.assertEqual([(x.kind, x.where, x.value) for x in found],
                         [("pl_missing", "J3", "=SUM(H3)-(I3*1.12)")])   # week 3 empty: left alone

    def test_a_different_formula_and_a_typed_number_are_only_reported(self):
        reps = [("Rep%d" % i, "", {}, ()) for i in range(7)]
        f = pnl(reps)
        f[2][6] = "=E3-F3"
        f[3][6] = "679"
        found = P.check_reps(f, f)
        self.assertEqual([(x.kind, x.fixable) for x in found],
                         [("pl_differs", False), ("pl_typed", False)])


class Totals(unittest.TestCase):
    def test_a_lost_weekly_total_comes_back_from_the_other_weeks(self):
        f = pnl([("Rep%d" % i, "", {}, ()) for i in range(6)])
        r = next(i for i, row in enumerate(f) if len(row) > 5 and row[5] == "Total Loss")
        f[r][9] = ""
        found = [x for x in P.check_totals(f, f) if x.fixable]
        self.assertEqual([(x.where, x.value) for x in found], [("J%d" % (r + 1), '=SUMIF(J3:J10,"<0")')])

    def test_the_expenses_row_is_never_touched(self):
        f = pnl([("Rep%d" % i, "", {}, ()) for i in range(6)])
        r = next(i for i, row in enumerate(f) if len(row) > 5 and row[5] == "Expenses")
        f[r][6] = "=$FJ$40"
        self.assertEqual([x for x in P.check_totals(f, f) if "expenses" in x.detail], [])

    def test_a_rep_added_under_the_range_stretches_it(self):
        f = pnl([("Rep%d" % i, "", {}, ()) for i in range(6)], spare=0)
        # the totals read rows 3..8; a rep is typed into the spacer row 9
        f[8] = ["", "", "New", "Rep"] + ["5", "1", "=SUM(E9)-(F9*1.12)"] + [""] * 15
        found = [x for x in P.check_totals(f, f) if x.kind == "range_short"]
        self.assertTrue(found)
        self.assertEqual(found[0].value, '=SUMIF(G3:G9,"<0")')

    def test_a_week_whose_total_skips_paid_rows_gets_the_other_weeks_range(self):
        f = pnl([("Rep%d" % i, "", {0: ("900", "300")}, ()) for i in range(6)])
        r = next(i for i, row in enumerate(f) if len(row) > 5 and row[5] == "Payroll")
        f[r][6] = "=SUM(F6:F10)"                                 # week 1 skips rows 3-5
        found = [x for x in P.check_totals(f, f) if x.where == "G%d" % (r + 1)]
        self.assertEqual([(x.kind, x.value) for x in found], [("range_short", "=SUM(F3:F10)")])

    def test_week_dates_chain(self):
        f = pnl([("Rep%d" % i, "", {}, ()) for i in range(6)])
        f[0][13] = "=#REF!+7"                                    # week 4's date (N1)
        found = [x for x in P.check_totals(f, f) if x.where == "N1"]
        self.assertEqual([x.value for x in found], ["=K1+7"])


if __name__ == "__main__":
    unittest.main()
