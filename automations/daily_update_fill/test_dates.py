"""Vantura master dates carry their year (Carlos 2026-11-19); owner boards keep m/d."""
import datetime as dt
import unittest

from automations.daily_update_fill import run as R


class Dates(unittest.TestCase):
    def test_with_year(self):
        self.assertEqual(R._with_year("11/20", dt.date(2026, 11, 18)), "11/20/2026")
        self.assertEqual(R._with_year("1/5", dt.date(2026, 12, 29)), "1/5/2027")    # crosses the year
        self.assertEqual(R._with_year("11/20/2025", dt.date(2026, 11, 18)), "11/20/2025")
        self.assertEqual(R._with_year("", dt.date(2026, 11, 18)), "")
        self.assertEqual(R._with_year("TBD", dt.date(2026, 11, 18)), "TBD")

    def test_mdy(self):
        self.assertEqual(R._mdy(dt.date(2026, 3, 4)), "3/4/2026")

    def test_orient_date_uses_a_written_year(self):
        today = dt.date(2026, 11, 19)
        self.assertEqual(R._orient_date("11/13/2025", today, True), dt.date(2025, 11, 13))
        self.assertEqual(R._orient_date("11/13/25", today, True), dt.date(2025, 11, 13))
        self.assertEqual(R._orient_date("11/13", today, True), dt.date(2026, 11, 13))
        # owner boards: exactly as before -- a written year is ignored
        self.assertEqual(R._orient_date("11/13/2025", today), dt.date(2026, 11, 13))
        self.assertEqual(R._orient_date("11/13", today), dt.date(2026, 11, 13))
        self.assertIsNone(R._orient_date("", today))

    def test_only_the_master(self):
        self.assertEqual(R.YEAR_DATES, {"Carlos Hidalgo"})
        self.assertEqual(R.DATE_FIELDS, ("date2", "orient"))


if __name__ == "__main__":
    unittest.main()
