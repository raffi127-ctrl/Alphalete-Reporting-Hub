"""Saturday knock boards stop at 6pm local for every office (Megan
2026-09-27), whatever the office's own Saturday hours say."""
import datetime as dt
import unittest

from automations.icd_alerts import knocks_post as K, offices as O

SAT = dt.date(2026, 10, 3)      # a Saturday
FRI = dt.date(2026, 10, 2)


def _office(sat_end="20:00"):
    base = next(iter(O.OFFICES.values()))
    return base._replace(saturday=True, sat_start="10:45", sat_end=sat_end,
                         day_start="13:30", day_end="21:00")


class SaturdayBoardStopTest(unittest.TestCase):
    def test_late_saturday_office_is_capped_at_six(self):
        o = _office("20:00")
        self.assertTrue(K.in_field_hours(o, dt.datetime.combine(SAT, dt.time(17, 59))))
        self.assertTrue(K.in_field_hours(o, dt.datetime.combine(SAT, dt.time(18, 0))))
        self.assertFalse(K.in_field_hours(o, dt.datetime.combine(SAT, dt.time(18, 1))))
        self.assertFalse(K.in_field_hours(o, dt.datetime.combine(SAT, dt.time(19, 30))))

    def test_weekday_untouched(self):
        o = _office("20:00")
        self.assertTrue(K.in_field_hours(o, dt.datetime.combine(FRI, dt.time(19, 30))))

    def test_earlier_office_hours_still_win(self):
        o = _office("16:00")
        self.assertFalse(K.in_field_hours(o, dt.datetime.combine(SAT, dt.time(17, 0))))

    def test_no_recap_after_the_cap(self):
        # A set-time office ending Saturday at 7:00 used to get a recap
        # window to 8:00; the cap closes it.
        o = _office("19:00")
        self.assertFalse(K._after_hours_slot(o, dt.datetime.combine(SAT, dt.time(19, 10))))
        # Friday recap after a 9:00 bell still works (9:00 slot, grace 40).
        self.assertTrue(K._after_hours_slot(o, dt.datetime.combine(FRI, dt.time(21, 10))))


if __name__ == "__main__":
    unittest.main()
