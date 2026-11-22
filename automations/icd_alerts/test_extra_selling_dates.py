"""EXTRA_SELLING_DATES: one office gets the alert hours on a date that is not
a selling day (Carlos's AT&T office, Sunday 2026-11-22); nobody else moves."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import config as C

CARLOS = [{"office_key": "carlos"}, {"office_key": "carlos-b2batt"}]
SUN = dt.datetime(2026, 11, 22, 14, 0)


class ExtraSellingDates(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(C, "EXTRA_SELLING_DATES", {"carlos-b2batt": {"2026-11-22"}})
        p.start()
        self.addCleanup(p.stop)

    def test_his_machine_alerts_that_sunday_on_the_weekday_clock(self):
        with mock.patch.object(C, "enrollments", return_value=CARLOS):
            self.assertTrue(C.in_selling_window(SUN))
            self.assertTrue(C.in_selling_window(SUN.replace(hour=10, minute=0)))
            self.assertTrue(C.in_selling_window(SUN.replace(hour=21, minute=30)))
            self.assertFalse(C.in_selling_window(SUN.replace(hour=21, minute=31)))
            self.assertFalse(C.in_selling_window(SUN.replace(hour=9, minute=59)))

    def test_only_that_date(self):
        with mock.patch.object(C, "enrollments", return_value=CARLOS):
            self.assertFalse(C.in_selling_window(dt.datetime(2026, 11, 29, 14, 0)))
            self.assertFalse(C.in_selling_window(dt.datetime(2026, 11, 15, 14, 0)))

    def test_every_other_machine_keeps_sunday_off(self):
        for key in ("cyrus", "raf", "carlos"):
            with mock.patch.object(C, "enrollments", return_value=[{"office_key": key}]):
                self.assertFalse(C.in_selling_window(SUN), key)

    def test_unreadable_enrollments_keep_sunday_off(self):
        with mock.patch.object(C, "enrollments", side_effect=OSError("boom")):
            self.assertFalse(C.in_selling_window(SUN))

    def test_his_weekdays_and_saturday_are_untouched(self):
        with mock.patch.object(C, "enrollments", return_value=CARLOS):
            fri = dt.datetime(2026, 11, 20, 21, 45)
            self.assertFalse(C.in_selling_window(fri))
            self.assertTrue(C.in_selling_window(fri.replace(hour=21, minute=30)))
            sat = dt.datetime(2026, 11, 21, 22, 59)
            self.assertTrue(C.in_selling_window(sat))          # his 11pm Saturday
            self.assertFalse(C.in_selling_window(sat.replace(hour=23, minute=1)))



class ExtraKnocksDates(unittest.TestCase):
    """EXTRA_KNOCKS_DATES: Raf's machine relays its knocks that Sunday (for the
    NDS board's '... GP' reps) WITHOUT getting the alert hours."""

    def setUp(self):
        p = mock.patch.object(C, "EXTRA_KNOCKS_DATES", {"raf": {"2026-11-22"}})
        p.start()
        self.addCleanup(p.stop)

    def test_rafs_machine_relays_knocks_that_day_only(self):
        with mock.patch.object(C, "enrollments", return_value=[{"office_key": "raf"}]):
            self.assertTrue(C.extra_knocks_day(SUN))
            self.assertFalse(C.extra_knocks_day(dt.datetime(2026, 11, 29, 14, 0)))
            # knocks only: his alert hours stay off that Sunday
            self.assertFalse(C.in_selling_window(SUN))

    def test_no_other_machine(self):
        for key in ("carlos-b2batt", "cyrus", "rafael"):
            with mock.patch.object(C, "enrollments", return_value=[{"office_key": key}]):
                self.assertFalse(C.extra_knocks_day(SUN), key)

    def test_unreadable_enrollments_mean_no(self):
        with mock.patch.object(C, "enrollments", side_effect=OSError("boom")):
            self.assertFalse(C.extra_knocks_day(SUN))


if __name__ == "__main__":
    unittest.main()
