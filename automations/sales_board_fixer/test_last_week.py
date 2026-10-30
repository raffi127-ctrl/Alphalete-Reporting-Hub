import datetime as dt
import unittest

from automations.sales_board_fixer import last_week as LW


def tab(reps, totals, hist=()):
    """A: -, B: #, C: name, D-E running (Apps, Int), F-G last, H-I prior,
    J-K MON (Apps, Int); TOTALS; history lines under it."""
    banner = ["", "", "", "RUNNING WEEK TOTALS", "", "LAST WEEK'S TOTALS", "",
              "PRIOR WEEK'S TOTALS", "", "MON", ""]
    sub = ["", "#", "WE", "Apps", "Int", "Apps", "Int", "Apps", "Int", "Apps", "Int"]
    rows = [banner, [""] * 11, sub]
    for i, (name, nums) in enumerate(reps):
        rows.append(["", i + 1, name] + list(nums))
    rows.append(["", "", "TOTALS"] + list(totals))
    rows.append([""] * 11)
    for label, nums in hist:
        rows.append(["", "", label] + list(nums))
    return rows


class LastWeek(unittest.TestCase):
    def test_late_sales_reach_last_week_totals_and_history(self):
        old = tab([("Ana Griffin (Wk 2)", [9, 4, 0, 0, 0, 0, 5, 2]),
                   ("Bo", [3, 1, 0, 0, 0, 0, 3, 1])], [12, 5, 0, 0, 0, 0, 8, 3])
        now = tab([("Ana Griffin (Wk 3)", [1, 1, 7, 4, 0, 0, 1, 1]),
                   ("Bo", [0, 0, 3, 1, 0, 0, 0, 0])], [1, 1, 10, 5, 0, 0, 1, 1],
                  hist=[("WE 10/19 - 10/25", [10, 5, 0, 0, 0, 0, 6, 3])])
        found = LW.check("Sales Board WE 11.1", now, now, now,
                         [("Sales Board WE 10.25", dt.date(2026, 10, 25), old, old,
                           "LAST WEEK'S TOTALS")])
        got = {x.where: x.value for x in found}
        self.assertEqual(got, {"F4": 9, "F6": 12, "D8": 12, "J8": 8})

    def test_a_formula_there_is_left_alone(self):
        old = tab([("Bo", [3, 1, 0, 0, 0, 0, 3, 1])], [3, 1, 0, 0, 0, 0, 3, 1])
        now = tab([("Bo", [0, 0, 2, 1, 0, 0, 0, 0])], [0, 0, 2, 1, 0, 0, 0, 0])
        f = [list(r) for r in now]
        f[3][5] = "=1+1"
        found = LW.check("Sales Board WE 11.1", now, f, now,
                         [("x", dt.date(2026, 10, 25), old, old, "LAST WEEK'S TOTALS")])
        self.assertEqual({x.where for x in found}, {"F5"})

    def test_tab_names(self):
        self.assertEqual(LW.week_sunday("Sales Board WE 11.1", dt.date(2026, 10, 30)),
                         dt.date(2026, 11, 1))
        self.assertEqual(LW.week_sunday("Sales Board WE 12.27", dt.date(2027, 1, 2)),
                         dt.date(2026, 12, 27))
        self.assertEqual(LW.older_titles("Sales Board WE 11.1",
                                         ["Sales Board WE 10.25", "Sales Board WE 10.18"],
                                         dt.date(2026, 10, 30)),
                         ("Sales Board WE 10.25", "Sales Board WE 10.18"))
