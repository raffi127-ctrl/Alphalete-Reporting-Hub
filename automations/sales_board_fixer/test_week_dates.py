"""python -m unittest automations.sales_board_fixer.test_week_dates"""
import datetime as dt
import unittest

from automations.sales_board_fixer import week_dates as W

TUE = dt.date(2026, 11, 3)
MON = dt.date(2026, 11, 2)


def board(label, numbers, long_names=False):
    """numbers: seven day numbers. long_names: under 'Monday', as Atef's board."""
    banner, row2, row3 = ["x", "KALKAN"], ["", ""], ["#", label]
    for word, long, n in zip(W._DAYS, ("Monday", "Tuesday", "Wednesday", "Thursday",
                                       "Friday", "Saturday", "Sunday"), numbers):
        banner += [word, long]
        row2 += ["", str(n)] if long_names else [str(n), ""]
        row3 += ["Apps", "Int"]
    return [banner, row2, row3, ["1", "Ana", "2", "1"], ["", "TOTALS", "2", "1"]]


GOOD = [2, 3, 4, 5, 6, 7, 8]


class Omar(unittest.TestCase):
    def test_the_case_that_started_it(self):
        v = board("WE9/7-9/13", [26, 27, 28, 29, 30, 31, 32])
        found = W.findings(v, " 11/08", TUE)
        self.assertEqual([(x.where, x.before, x.after) for x in found],
                         [("C2", "26", "2"), ("B3", "WE9/7-9/13", "WE 11/2-11/8")])
        self.assertIn("MON says 26 (should be 2)", W.warning_line(found))

    def test_fixed_tab_is_clean(self):
        self.assertEqual(W.findings(board("WE11/2-11/8", GOOD), " 11/08", TUE), [])


class WeekFromName(unittest.TestCase):
    def test_monday_named_and_sunday_named_are_the_same_week(self):
        for name in ("11.2", "WE 11/2", "11.08", "Sales Board W.E 11.8"):
            self.assertEqual(W.week_of(name, TUE), MON, name)

    def test_last_week_tab_checked_against_its_own_week(self):
        v = board("WE10/26-11/01", [26, 27, 28, 29, 30, 31, 1])
        self.assertEqual(W.findings(v, "11/01", TUE), [])

    def test_old_named_tab_is_not_the_current_board(self):
        self.assertEqual(W.findings(board("WE 6/8 - 6/14", [8, 9, 10, 11, 12, 13, 14]),
                                    "w.e 10/12/26", TUE), [])


class Undated(unittest.TestCase):
    def test_stale_reused_board_is_flagged(self):
        found = W.findings(board("Road to TOP 5", [6, 7, 8, 9, 10, 11, 12]), "NEW Sales Board", TUE)
        self.assertEqual([x.before for x in found], ["6"])

    def test_monday_morning_last_week_passes(self):
        v = board("x", [26, 27, 28, 29, 30, 31, 1])
        self.assertEqual(W.findings(v, "Sales Board", MON), [])
        self.assertTrue(W.findings(v, "Sales Board", TUE))


class Days(unittest.TestCase):
    def test_number_under_the_long_name(self):
        self.assertEqual(W.findings(board("x", GOOD, long_names=True), "WE 11.08", TUE), [])
        self.assertTrue(W.findings(board("x", [9] + GOOD[1:], long_names=True), "WE 11.08", TUE))

    def test_off_by_one_says_it_once(self):
        found = W.findings(board("WE 11/2-11/8", [1, 2, 3, 4, 5, 6, 7]), "11.2", TUE)
        self.assertEqual([x.before for x in found], ["1"])

    def test_one_bad_day_later_in_the_week(self):
        found = W.findings(board("x", [2, 3, 4, 5, 6, 7, 23]), "COLTEN", TUE)
        self.assertEqual([(x.before, x.after) for x in found], [("23", "8")])

    def test_formula_past_month_end_passes(self):
        self.assertEqual(W.findings(board("WE10/26-11/01", [26, 27, 28, 29, 30, 31, 32]),
                                    "11/01", TUE), [])

    def test_no_day_numbers_nothing_to_check(self):
        v = board("x", ["", "", "", "", "", "", ""])
        self.assertEqual(W.findings(v, "Sales Board", TUE), [])


class Label(unittest.TestCase):
    def check(self, label):
        return [x.before for x in W.findings(board(label, GOOD), "WE 11.08", TUE)]

    def test_right_spellings(self):
        for label in ("WE 11/2-11/8", "WE11/2 - 11/08", "11/02-11/08", "11/8/2026",
                      "Falling asleep", '"Proud but Never Satisfied"'):
            self.assertEqual(self.check(label), [], label)

    def test_wrong_ones(self):
        for label in ("WE 11/-2-11/8", "WE 11/2-11/9", "WE 6/8 - 6/14"):
            self.assertEqual(self.check(label), [label], label)


if __name__ == "__main__":
    unittest.main()
