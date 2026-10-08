import datetime as dt
import unittest

from automations.recruiting_report import badged


class WeeksTest(unittest.TestCase):
    def test_last_four_closed_weeks(self):
        # Thu 10/8: the 10/4 week is still running, so it's 9/6..9/27.
        got = badged.weeks_to_write(dt.date(2026, 10, 8))
        self.assertEqual(got, [dt.date(2026, 9, 6), dt.date(2026, 9, 13),
                               dt.date(2026, 9, 20), dt.date(2026, 9, 27)])

    def test_sunday_counts_its_own_week_as_running(self):
        self.assertEqual(badged.weeks_to_write(dt.date(2026, 10, 4))[-1],
                         dt.date(2026, 9, 27))


class SheetColTest(unittest.TestCase):
    def test_ov_week_lands_in_the_following_sunday_column(self):
        # find_sunday_columns is 1-indexed: 10/4 header in column D (4) -> 0-based 3
        cols = {dt.date(2026, 9, 27): 3, dt.date(2026, 10, 4): 4}
        self.assertEqual(badged.sheet_col(cols, dt.date(2026, 9, 27)), 3)
        self.assertIsNone(badged.sheet_col(cols, dt.date(2026, 10, 4)))


class ParseTest(unittest.TestCase):
    def test_badged_by_week(self):
        got = badged.parse_weeks({"data": {"weeks": [
            {"wk": "2026-09-27", "badged": 5.0}, {"wk": "2026-10-04", "badged": None}]}})
        self.assertEqual(got, {dt.date(2026, 9, 27): 5, dt.date(2026, 10, 4): 0})

    def test_no_weeks_is_no_data_not_zeros(self):
        self.assertIsNone(badged.parse_weeks({"data": {"success": True, "weeks": []}}))
        self.assertIsNone(badged.parse_weeks({"error": 403}))


class RowsTest(unittest.TestCase):
    def test_opt_new_start_retention_not_the_recruiting_one(self):
        col_b = ["WE SUNDAY", "New Starts Showed", "New Start Retention", "",
                 "OPT", "New Starts by EOW", "New Start Retention", "New Internets"]
        rows = badged.find_rows(col_b)
        self.assertEqual((rows["ns_showed"], rows["opt"], rows["opt_nsr"]), (2, 5, 7))
        self.assertIsNone(rows["badged"])


if __name__ == "__main__":
    unittest.main()
