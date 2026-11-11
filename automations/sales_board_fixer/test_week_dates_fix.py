"""python -m unittest automations.sales_board_fixer.test_week_dates_fix

Eve 2026-11-03: a tab with a date in its name gets its dates corrected; a tab
with no date only warns."""
import datetime as dt
import unittest

from automations.sales_board_fixer import checks as K, run as R, week_dates as W
from automations.sales_board_fixer.test_week_dates import TUE, board


def chain(v):
    """The real boards: Monday typed, the other days =prev+1."""
    f = [list(r) for r in v]
    days = [c for c, x in enumerate(v[1]) if str(x).strip()]
    for prev, c in zip(days, days[1:]):
        f[1][c] = "=%s2+1" % K.col_letter(prev + 1)
    return f


def cells(found):
    return [(x.where, x.value) for x in found]


class DatedTab(unittest.TestCase):
    def test_cy_monday_typed_wrong_writes_only_monday(self):
        v = board("WE 11/2-11/8", [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(cells(W.findings(v, "11.2", TUE, chain(v))), [("C2", "2")])

    def test_stale_date_and_label_both_get_written(self):
        v = board("WE9/7-9/13", [26, 27, 28, 29, 30, 31, 32])
        self.assertEqual(cells(W.findings(v, " 11/08", TUE, chain(v))),
                         [("C2", "2"), ("B3", "WE 11/2-11/8")])

    def test_seven_typed_days_all_get_written(self):
        v = board("WE 11/2-11/8", [1, 2, 3, 4, 5, 6, 7])
        got = W.findings(v, "11.2", TUE, [list(r) for r in v])
        self.assertEqual([x.value for x in got], ["2", "3", "4", "5", "6", "7", "8"])

    def test_a_monday_that_is_a_formula_only_warns(self):
        v = board("WE 11/2-11/8", [1, 2, 3, 4, 5, 6, 7])
        f = chain(v)
        f[1][2] = "=TODAY()"
        self.assertEqual(cells(W.findings(v, "11.2", TUE, f)), [("C2", None)])

    def test_a_label_that_is_a_formula_only_warns(self):
        v = board("WE9/7-9/13", [2, 3, 4, 5, 6, 7, 8])
        f = chain(v)
        f[2][1] = '="WE "&A1'
        self.assertEqual(cells(W.findings(v, "11.2", TUE, f)), [("B3", None)])

    def test_right_dates_write_nothing(self):
        v = board("WE 11/2-11/8", [2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(W.findings(v, "11.2", TUE, chain(v)), [])

    def test_month_end_chain_is_left_alone(self):
        today = dt.date(2026, 11, 24)
        v = board("WE 11/23-11/29", [23, 24, 25, 26, 27, 28, 29])
        self.assertEqual(W.findings(v, "11.23", today, chain(v)), [])

    def test_an_old_tab_is_not_touched(self):
        v = board("WE 1/1-1/7", [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(W.findings(v, "10.12", TUE, chain(v)), [])


def sold_on(v, days):
    """Put a sale for Ana under each day index in days (and nowhere else)."""
    v = [list(r) for r in v]
    ana = v[3]
    for c in range(2, len(ana)):
        ana[c] = ""
    for d in days:
        c = 2 + 2 * d
        while len(ana) <= c:
            ana.append("")
        ana[c] = "3"
    return v


class UndatedTab(unittest.TestCase):
    def test_cody_sales_board_warns_and_writes_nothing(self):
        # Thursday has sales on a Tuesday: last week's board, not rolled yet
        v = sold_on(board("WE 6/8 - 6/14", [8, 9, 10, 11, 12, 13, 14]), [0, 3])
        got = W.findings(v, "Sales Board", TUE, chain(v))
        self.assertEqual(len(got), 2)
        self.assertFalse(any(x.fixable for x in got))

    def test_rolled_board_gets_this_weeks_dates(self):
        # Eve 11/11: Mon+Tue sold, Wed-Sun empty on a Wednesday = this week
        wed = dt.date(2026, 11, 11)
        v = sold_on(board("WE 11/2-11/8", [2, 3, 4, 5, 6, 7, 8]), [0, 1])
        got = W.findings(v, "Sales Board", wed, chain(v))
        self.assertEqual(cells(got), [("C2", "9"), ("B3", "WE 11/9-11/15")])

    def test_rolled_needs_an_earlier_sale(self):
        v = sold_on(board("x", [26, 27, 28, 29, 30, 31, 1]), [])
        got = W.findings(v, "Sales Board", TUE, chain(v))
        self.assertTrue(got)
        self.assertFalse(any(x.fixable for x in got))

    def test_rolled_never_on_monday_or_weekend(self):
        v = sold_on(board("x", [6, 7, 8, 9, 10, 11, 12]), [0])
        for day in (dt.date(2026, 11, 7), dt.date(2026, 11, 8)):
            self.assertFalse(W.rolled_this_week(v, day), day)
        self.assertTrue(W.rolled_this_week(v, TUE))

    def test_copy_of_tab_warns_and_writes_nothing(self):
        v = board("WE 10/26-11/1", [26, 27, 28, 29, 30, 31, 32])
        got = W.findings(v, "Copy of WE 11/1/26", TUE, chain(v))
        self.assertTrue(got)
        self.assertFalse(any(x.fixable for x in got))


class Warning(unittest.TestCase):
    def test_only_what_lucy_does_not_write_goes_to_the_dm(self):
        fixed = K.Finding("date_wrong", "11.2", "C2", "", before="1", after="2", value="2")
        kept = K.Finding("date_wrong", "Sales Board", "B3", "label says x", before="x", after="y")
        rows = R._dated_rows("Ana", "id", {"a": [fixed], "b": [kept]})
        self.assertEqual([r[2] for r in rows], ["Sales Board"])

    def test_owners_boards_may_write_dates(self):
        self.assertIn("date_wrong", R.OWNER_KINDS)


if __name__ == "__main__":
    unittest.main()
