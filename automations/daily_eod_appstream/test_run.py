"""python -m unittest automations.daily_eod_appstream.test_run"""
import datetime as dt
import unittest

from automations.daily_eod_appstream import run


def _raw(**per_day):
    """per_day: day -> (b1, s1, b2nd, b2, s2)."""
    keys = list(run.FIELDS)
    out = {k: {} for k in keys}
    for day, vals in per_day.items():
        for k, v in zip(keys, vals):
            out[k][day] = v
    return out


class Math(unittest.TestCase):
    def test_perli_sheet_andre_burton_monday(self):
        # Perli's sheet, W/E 10/04, Monday: 43 21 49% | 3 14% | 8 5 63%
        r = run.day_row(_raw(monday=(43, 21, 3, 8, 5)), "monday")
        self.assertEqual(run.whole_pct(run.pct(r["s1"], r["b1"])), 49)
        self.assertEqual(run.whole_pct(run.pct(r["b2nd"], r["s1"])), 14)
        self.assertEqual(run.whole_pct(run.pct(r["s2"], r["b2"])), 63)

    def test_report_day_is_yesterday_and_monday_reports_saturday(self):
        self.assertEqual(run.report_day_for(dt.date(2026, 10, 7)), dt.date(2026, 10, 6))
        self.assertEqual(run.report_day_for(dt.date(2026, 10, 12)), dt.date(2026, 10, 10))
        self.assertEqual(run.report_day_for(dt.date(2026, 10, 6)), dt.date(2026, 10, 5))

    def test_days_accumulate_monday_to_report_day(self):
        self.assertEqual(run.shown_days(dt.date(2026, 10, 5)), [dt.date(2026, 10, 5)])
        sat = run.shown_days(dt.date(2026, 10, 10))
        self.assertEqual((sat[0], sat[-1], len(sat)), (dt.date(2026, 10, 5), sat[-1], 6))

    def test_table_has_one_group_per_day_plus_totals(self):
        row = {"b1": 10, "s1": 5, "b2nd": 2, "b2": 4, "s2": 1}
        out = run.table_html([("Monday 10/5", {"A": row}), ("Tuesday 10/6", {"A": row}),
                              ("WEEKLY TOTALS", {"A": run.sum_rows([row, row])})])
        self.assertIn("WEEKLY TOTALS", out)
        self.assertIn(">20<", out)                      # 10 + 10 1st B

    def test_red_is_under_50_and_no_booked_is_not_red(self):
        today = {
            "Zed": {"b1": 0, "s1": 0, "b2nd": 0, "b2": 10, "s2": 4},   # 40% red
            "Amy": {"b1": 0, "s1": 0, "b2nd": 0, "b2": 10, "s2": 5},   # 50% green
            "Bob": {"b1": 0, "s1": 0, "b2nd": 0, "b2": 0, "s2": 0},    # no %
            "abe": {"b1": 0, "s1": 0, "b2nd": 0, "b2": 3, "s2": 1},    # 33% red
        }
        self.assertEqual([o for o, _ in run.red_list(today)], ["abe", "Zed"])


if __name__ == "__main__":
    unittest.main()
