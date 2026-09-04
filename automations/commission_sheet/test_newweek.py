"""Which files in the shared commission folder are the live weekly series.

Every name here is real, taken from the folder on 2026-09-04. Getting this
wrong either builds a week's payroll on a demo copy or archives somebody
else's work, so the whole list is pinned. Offline — no Drive access.

    python -m unittest automations.commission_sheet.test_newweek
"""
import datetime as dt
import unittest

from automations.commission_sheet.newweek import (
    _name_for, _parse_week, _week_of, is_live_sheet)


class LiveSeries(unittest.TestCase):
    def test_plain_weekly_names(self):
        self.assertEqual(is_live_sheet("RH 8.9"), (8, 9))
        self.assertEqual(is_live_sheet("RH 1.7.xlsx"), (1, 7))

    def test_leading_space_and_person_suffix_still_count(self):
        # These ARE the live workbooks despite reading like practice copies
        # (Megan, 2026-09-04).
        self.assertEqual(is_live_sheet(" RH 8.30-Alisson"), (8, 30))
        self.assertEqual(is_live_sheet(" RH 8.2"), (8, 2))

    def test_practice_copies_are_never_live(self):
        self.assertIsNone(is_live_sheet("RH 8.30 Practice"))
        self.assertIsNone(is_live_sheet(" RH 7.19 PRACTICE"))

    def test_other_peoples_series_and_templates_excluded(self):
        for name in ("AC 8/30", "AC 8/23", "CH WE 7.12.xlsx",
                     "Commission sheet template", "Commission Sheet 2.0 Template",
                     "Kastle access", "Base Gurantee / Friday Paychecks / Glassdoor",
                     "Carlos", "Rafael", "Atef"):
            self.assertIsNone(is_live_sheet(name), name)

    def test_lookalikes_excluded(self):
        # A PDF that happens to start with RH- lives elsewhere in Drive.
        self.assertIsNone(
            is_live_sheet("RH-1541677-invoice-2026-08-03 - Laysha Polanco.pdf"))
        self.assertIsNone(is_live_sheet("RH 13.5"))   # not a month
        self.assertIsNone(is_live_sheet("RHINO 8.9"))


class WeekOfFile(unittest.TestCase):
    def test_year_comes_from_created_date(self):
        f = {"name": "RH 8.30-Alisson", "createdTime": "2026-09-03T12:00:00Z"}
        self.assertEqual(_week_of(f), dt.date(2026, 8, 30))

    def test_december_week_created_in_january_keeps_its_own_year(self):
        f = {"name": "RH 12.28", "createdTime": "2026-01-05T12:00:00Z"}
        self.assertEqual(_week_of(f), dt.date(2025, 12, 28))

    def test_january_week_created_in_december_rolls_forward(self):
        f = {"name": "RH 1.3", "createdTime": "2025-12-30T12:00:00Z"}
        self.assertEqual(_week_of(f), dt.date(2026, 1, 3))

    def test_non_series_file_has_no_week(self):
        self.assertIsNone(
            _week_of({"name": "AC 8/30", "createdTime": "2026-09-03T12:00:00Z"}))


class Naming(unittest.TestCase):
    def test_new_name_is_unpadded(self):
        self.assertEqual(_name_for(dt.date(2026, 9, 6)), "RH 9.6")
        self.assertEqual(_name_for(dt.date(2026, 12, 27)), "RH 12.27")

    def test_week_argument_forms(self):
        self.assertEqual(_parse_week("9.6").month, 9)
        self.assertEqual(_parse_week("9/6").day, 6)
        self.assertEqual(_parse_week("9.6.2026"), dt.date(2026, 9, 6))

    def test_bad_week_argument_rejected(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_week("next sunday")


if __name__ == "__main__":
    unittest.main()
