"""Tests for the day-number row: month-end safety + the repair planner.

WHY: the day-number row under each section's Monday…Sunday header shipped as a
chain (`=<prev>+1`), and a chain cannot cross a month end — 31 + 1 = 32. On
2026-09-02 the week of Mon 8/31 read `31 32 33 34 35 36 37` on BOTH boards of
the 1IpDs2 workbook, no column matched 9/1, and the ORG board dropped seven
sections and did not post.

So the cases that matter here are the boundaries: a week that straddles a month
end (long and short months, and February), a mirror row that must be left
alone, and the self-chaining row a hand repair leaves behind.

Run:  .venv/bin/python -m pytest automations/org_sales_board/test_daynum_repair.py
  or  .venv/bin/python -m unittest automations.org_sales_board.test_daynum_repair
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.org_sales_board import daynum_repair as dr
from automations.org_sales_board import fill_section as fs


HDR = ["Retail NL", "", "Monday", "Tuesday", "Wednesday", "Thursday",
       "Friday", "Saturday", "Sunday", "RUNNING WEEK TOTALS"]


def _tab(daynum_vals, daynum_forms, label="Retail NL"):
    """A one-section grid: header, day-number row, one ICD row, Totals."""
    hdr = list(HDR)
    hdr[0] = label
    grid = [hdr,
            ["", ""] + [str(v) for v in daynum_vals] + [""],
            ["1", "Some ICD"] + [""] * 8,
            ["Totals", ""] + [""] * 8]
    form = [hdr,
            ["", ""] + list(daynum_forms) + [""],
            ["1", "Some ICD"] + [""] * 8,
            ["Totals", ""] + [""] * 8]
    return grid, form


class DaynumValues(unittest.TestCase):
    def test_week_inside_one_month(self):
        self.assertEqual(fs.daynum_row_values(dt.date(2026, 8, 24)),
                         [24, 25, 26, 27, 28, 29, 30])

    def test_week_straddling_a_31_day_month_end(self):
        """The 2026-09-02 incident: Mon 8/31 must wrap to 1, not run to 37."""
        self.assertEqual(fs.daynum_row_values(dt.date(2026, 8, 31)),
                         [31, 1, 2, 3, 4, 5, 6])

    def test_week_straddling_a_30_day_month_end(self):
        self.assertEqual(fs.daynum_row_values(dt.date(2026, 9, 28)),
                         [28, 29, 30, 1, 2, 3, 4])

    def test_week_straddling_february(self):
        self.assertEqual(fs.daynum_row_values(dt.date(2027, 2, 22)),
                         [22, 23, 24, 25, 26, 27, 28])

    def test_week_straddling_a_year_end(self):
        self.assertEqual(fs.daynum_row_values(dt.date(2026, 12, 28)),
                         [28, 29, 30, 31, 1, 2, 3])


class RepairPlan(unittest.TestCase):
    TUE = dt.date(2026, 9, 1)      # reporting week = Mon 8/31 … Sun 9/6

    def test_broken_chain_is_rewritten_to_literals(self):
        grid, form = _tab([31, 32, 33, 34, 35, 36, 37],
                          [31, "=C2+1", "=D2+1", "=E2+1", "=F2+1", "=G2+1",
                           "=H2+1"])
        upd = dr.plan(grid, form, today=self.TUE)
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["range"], "C2:I2")
        self.assertEqual(upd[0]["values"], [[31, 1, 2, 3, 4, 5, 6]])

    def test_correct_literals_are_left_alone(self):
        grid, form = _tab([31, 1, 2, 3, 4, 5, 6], [31, 1, 2, 3, 4, 5, 6])
        self.assertEqual(dr.plan(grid, form, today=self.TUE), [])

    def test_right_numbers_but_a_live_chain_is_still_repaired(self):
        """The 2026-09-02 mid-repair trap: someone types the correct `1` over
        ONE cell and the row READS perfectly — while the chain still runs from
        the next cell on, so the next roll freezes it. Values alone can't see
        this."""
        grid, form = _tab([31, 1, 2, 3, 4, 5, 6],
                          [31, 1, "=D2+1", "=E2+1", "=F2+1", "=G2+1", "=H2+1"])
        upd = dr.plan(grid, form, today=self.TUE)
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["values"], [[31, 1, 2, 3, 4, 5, 6]])

    def test_mirror_row_is_never_touched(self):
        """`=C77 =D77 …` is correct by construction — fixing its source fixes
        it. Rewriting these to a chain is how the 8/9 incident got a SECOND
        broken row."""
        grid, form = _tab([31, 32, 33, 34, 35, 36, 37],
                          ["=C77", "=D77", "=E77", "=F77", "=G77", "=H77",
                           "=I77"])
        self.assertEqual(dr.plan(grid, form, today=self.TUE), [])

    def test_self_chaining_row_becomes_a_full_mirror(self):
        """Mirrors in col C then chains off itself — the shape a hand repair
        leaves behind (row 1580 on the live board)."""
        grid, form = _tab([31, 32, 33, 34, 35, 36, 37],
                          ["=C77", "=C2+1", "=D2+1", "=E2+1", "=F2+1",
                           "=G2+1", "=H2+1"])
        upd = dr.plan(grid, form, today=self.TUE)
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["values"],
                         [["=C77", "=D77", "=E77", "=F77", "=G77", "=H77",
                           "=I77"]])

    def test_sunday_first_section_gets_its_own_week(self):
        """A Sun–Sat section (Frontier) starts a day BEFORE the reporting
        Monday — it must not be 'fixed' onto Monday."""
        hdr = ["Frontier", "", "Sunday", "Monday", "Tuesday", "Wednesday",
               "Thursday", "Friday", "Saturday", "RUNNING WEEK TOTALS"]
        grid = [hdr, ["", "", "30", "31", "32", "33", "34", "35", "36", ""],
                ["1", "Some ICD"] + [""] * 8, ["Totals", ""] + [""] * 8]
        form = [hdr, ["", "", 30, "=C2+1", "=D2+1", "=E2+1", "=F2+1", "=G2+1",
                      "=H2+1", ""],
                ["1", "Some ICD"] + [""] * 8, ["Totals", ""] + [""] * 8]
        upd = dr.plan(grid, form, today=self.TUE)
        self.assertEqual(upd[0]["values"], [[30, 31, 1, 2, 3, 4, 5]])


if __name__ == "__main__":
    unittest.main()
