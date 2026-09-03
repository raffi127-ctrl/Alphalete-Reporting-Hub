"""The Delta % cells of a delta box must be FORMULAS, every day, for good.

Eve, 2026-09-03, after finding 616 of them frozen since the 2026-08-26 clobber:
"aplicalo como regla para que no se vuelva a romper la semana que viene ...
tiene que ir variando segun la comparacion de ventas de la semana en curso vs
la semana anterior, no puede ser valor fijo".

A clean board planning zero writes only proves idempotence, which is the easy
half — the repair reported `0 to rewrite` on a board with 616 dead cells for a
week. So these build a synthetic box, freeze cells one at a time, and assert the
planner asks for exactly those back, comparing exactly this week against last.

Offline: no Sheet, no Tableau.
"""
from __future__ import annotations

import unittest

from automations.org_sales_board import delta_formula_repair as dfr
from automations.org_sales_board import rollover as ro

# A | rank · B | rep · C/D/E week triplet · then one triplet per day:
# F/G/H Monday, I/J/K Tuesday, L/M/N Wednesday.
HDR = ["", "", "Total this week", "Last week", "Delta",
       "This week", "Last week", "Delta",
       "This week", "Last week", "Delta",
       "This week", "Last week", "Delta"]
DAY_COLS = (6, 9, 12)
REP_ROW, TOT_ROW = 3, 4


def _rep(r: int, freeze=()):
    row = ["1", "A Rep",
           "=F%d+I%d+L%d" % (r, r, r), "=G%d+J%d+M%d" % (r, r, r),
           "=Iferror((C%d-D%d)/D%d,0)" % (r, r, r)]
    for c in DAY_COLS:
        a, b = ro.a1col(c), ro.a1col(c + 1)
        row += ['=SUMIF($B$10:$B$12,"A Rep",$C$10:$C$12)', "7",
                "=Iferror((%s%d-%s%d)/%s%d,0)" % (a, r, b, r, b, r)]
    for c in freeze:
        row[c - 1] = "-1"
    return row


def _totals(r: int):
    row = ["", "", "=SUM(C3:C3)", "=SUM(D3:D3)",
           "=Iferror((C%d-D%d)/D%d,0)" % (r, r, r)]
    for c in DAY_COLS:
        a, b = ro.a1col(c), ro.a1col(c + 1)
        row += ["=SUM(%s3:%s3)" % (a, a), "=SUM(%s3:%s3)" % (b, b),
                "=Iferror((%s%d-%s%d)/%s%d,0)" % (a, r, b, r, b, r)]
    return row


def _board(freeze=()):
    rows = [[""] * len(HDR), HDR[:], _rep(REP_ROW, freeze), _totals(TOT_ROW)]
    return rows, [r[:] for r in rows]      # (values, formulas)


class FindsTheBox(unittest.TestCase):
    def test_triplets(self):
        tables = ro.find_delta_tables(_board()[0])
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["this_cols"], list(DAY_COLS))
        self.assertEqual(tables[0]["data_rows"], [REP_ROW])


class PlansOnlyWhatIsFrozen(unittest.TestCase):
    def test_clean_board_plans_nothing(self):
        v, f = _board()
        self.assertEqual(dfr.plan_delta_pct(v, f), [])

    def test_one_frozen_day_comes_back(self):
        v, f = _board(freeze=(14,))            # Wednesday's Delta, col N
        got = dfr.plan_delta_pct(v, f)
        self.assertEqual([u["range"] for u in got], ["N3"])
        # THIS week (L) against LAST week (M) — the comparison Eve specified.
        self.assertEqual(got[0]["values"][0][0], "=Iferror((L3-M3)/M3,0)")

    def test_every_delta_cell_is_watched(self):
        # the weekly one AND all three per-day ones
        v, f = _board(freeze=(5, 8, 11, 14))
        self.assertEqual([u["range"] for u in dfr.plan_delta_pct(v, f)],
                         ["E3", "H3", "K3", "N3"])

    def test_totals_row_is_covered(self):
        v, f = _board()
        f[TOT_ROW - 1][4] = "-0.5714"
        self.assertEqual([u["range"] for u in dfr.plan_delta_pct(v, f)], ["E4"])

    def test_lowercase_iferror_is_live_not_churn(self):
        # One row on the live board carries '=iferror(' in lower case. It is
        # just as live; rewriting it every morning would never converge.
        v, f = _board()
        f[REP_ROW - 1][7] = "=iferror((F3-G3)/G3,0)"
        self.assertEqual(dfr.plan_delta_pct(v, f), [])

    def test_a_sumif_is_not_mistaken_for_a_delta(self):
        # Freezing a 'This week' cell is a DIFFERENT defect with a different
        # repair (it needs the daily table); this planner must leave it alone.
        v, f = _board(freeze=(6,))
        self.assertEqual(dfr.plan_delta_pct(v, f), [])


if __name__ == "__main__":
    unittest.main()
