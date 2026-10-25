"""An office that asked for a later Saturday keeps its alerts past 5pm; every
other machine keeps the default window (Steve, 2026-10-24)."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import config as C


class SellingEndOverride(unittest.TestCase):
    SAT = dt.datetime(2026, 10, 24, 18, 30)     # a Saturday, 6:30pm

    def test_default_saturday_ends_at_five(self):
        with mock.patch.object(C, "enrollments", return_value=[{"office_key": "cyrus"}]):
            self.assertFalse(C.in_selling_window(self.SAT))
            self.assertTrue(C.in_selling_window(self.SAT.replace(hour=16, minute=59)))

    def test_steves_machine_runs_to_eight_thirty_on_saturday(self):
        with mock.patch.object(C, "enrollments", return_value=[{"office_key": "steve"}]):
            self.assertTrue(C.in_selling_window(self.SAT))
            self.assertTrue(C.in_selling_window(self.SAT.replace(hour=20, minute=30)))
            self.assertFalse(C.in_selling_window(self.SAT.replace(hour=20, minute=31)))

    def test_weekdays_are_untouched(self):
        fri = dt.datetime(2026, 10, 23, 21, 45)
        with mock.patch.object(C, "enrollments", return_value=[{"office_key": "steve"}]):
            self.assertFalse(C.in_selling_window(fri))
            self.assertTrue(C.in_selling_window(fri.replace(hour=21, minute=30)))

    def test_unreadable_enrollments_keep_the_default(self):
        with mock.patch.object(C, "enrollments", side_effect=OSError("boom")):
            self.assertFalse(C.in_selling_window(self.SAT))


if __name__ == "__main__":
    unittest.main()
