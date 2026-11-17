import datetime as dt
import unittest

from automations.raf_all_in_one_focus import ars_weekly


def _box(label, people):
    """Two blocks side by side: QUALIFIED at col 2, ANSWERED at col 10."""
    head = ["", "", label, "Monday", "TOTAL for the WEEK", "", "", "", "", "",
            label, "Monday", "TOTAL for the WEEK", "", "", ""]
    sub = ["", "", "Interviewer", "Q", "Qualified", "Disqualified", "Declined",
           "Qualified Retention", "", "",
           "Interviewer", "Q", "Qualified", "Answered", "Booked", "Not Contacted"]
    rows = [head, sub]
    for name, q, di, de, a, b, nc in people:
        rows.append(["x", "", name, "1", str(q), str(di), str(de), "70%", "", "",
                     name, "1", str(q), str(a), str(b), str(nc)])
    return rows


class WeeklyTotals(unittest.TestCase):
    def test_sums_every_interviewer_per_week(self):
        row1 = ["Owner", "", "QUALIFIED RETENTION", "", "", "", "", "", "", "",
                "ANSWERED / BOOKED RETENTION", "", "", "", "", ""]
        rows = [row1]
        rows += _box("11/8", [("Ana", 10, 2, 1, 9, 8, 0), ("Owner", 0, 3, 1, 0, 0, 0)])
        rows += _box("11/15", [("Ana", 5, 1, 0, 5, 4, 1)])
        rows.append(["log row only", "", "", "99", "99"])     # no interviewer: ignored
        t = ars_weekly.weekly_totals(rows, dt.date(2026, 11, 17))
        self.assertEqual(t[dt.date(2026, 11, 8)],
                         {"qualified": 10, "disqualified": 5, "declined": 2,
                          "ab_qualified": 10, "answered": 9, "booked": 8,
                          "not_contacted": 0})
        self.assertEqual(t[dt.date(2026, 11, 15)]["not_contacted"], 1)

    def test_week_label_year(self):
        self.assertEqual(ars_weekly.week_date("12/27", dt.date(2027, 1, 5)),
                         dt.date(2026, 12, 27))
        self.assertEqual(ars_weekly.week_date("1/3", dt.date(2026, 12, 30)),
                         dt.date(2027, 1, 3))
        self.assertIsNone(ars_weekly.week_date("Monday", dt.date(2026, 11, 17)))


if __name__ == "__main__":
    unittest.main()
