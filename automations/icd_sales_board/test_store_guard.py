"""The store refuses a mis-dated week. No network."""
import datetime as dt
import unittest

from automations.icd_sales_board import tableau_days as TD

TODAY = dt.date(2026, 9, 22)
MON = dt.date(2026, 9, 14)


def week(per_day):
    """{date: units} for Mon..Sun from a list of seven numbers."""
    return {MON + dt.timedelta(days=i): n for i, n in enumerate(per_day)}


class StoreGuardTests(unittest.TestCase):
    def test_a_real_week_is_accepted(self):
        # Raf's corrected week: weekdays 40-56, Sunday 3.
        self.assertEqual(TD.looks_misdated(week([52, 40, 56, 48, 45, 48, 3]),
                                           TODAY), "")

    def test_the_shifted_week_is_refused(self):
        # What the 2am job wrote before the fix: weekday volume on Sunday.
        why = TD.looks_misdated(week([83, 93, 87, 88, 72, 66, 83]), TODAY)
        self.assertIn("Sunday", why)

    def test_a_future_date_is_refused(self):
        self.assertIn("future", TD.looks_misdated(
            {TODAY + dt.timedelta(days=3): 40}, TODAY))

    def test_a_partial_week_is_fine(self):
        # Tuesday's run: only Monday has settled, Sunday is empty.
        self.assertEqual(TD.looks_misdated(week([111, 0, 0, 0, 0, 0, 0]),
                                           TODAY), "")

    def test_a_small_sunday_is_never_refused(self):
        # Under 20 units on a Sunday is a normal Sunday, whatever the weekdays.
        self.assertEqual(TD.looks_misdated(week([10, 8, 9, 7, 6, 5, 12]),
                                           TODAY), "")


if __name__ == "__main__":
    unittest.main()
