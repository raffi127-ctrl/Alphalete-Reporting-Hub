"""A set-time board may post after the bell, within the slot's grace
(Colten's 9:00 PM never posted behind an 8:30 end, 2026-09-22)."""
import datetime as dt
import unittest

from automations.icd_alerts import knocks_post as K, offices as O


def _office(day_end="20:30", saturday=True):
    return O.AlertOffice(key="colten", owner="Colten Wright", label="x", channels=(),
                         timezone="America/New_York", day_start="13:30", day_end=day_end,
                         sat_start="11:30", sat_end="19:00", saturday=saturday)


class RecapAfterHoursTest(unittest.TestCase):
    def test_nine_pm_behind_an_830_end_is_a_recap(self):
        now = dt.datetime(2026, 9, 22, 21, 5)      # Tuesday
        self.assertTrue(K._after_hours_slot(_office(), now))

    def test_inside_hours_is_not_a_recap(self):
        self.assertFalse(K._after_hours_slot(_office(), dt.datetime(2026, 9, 22, 17, 20)))

    def test_too_long_after_the_bell_is_not(self):
        self.assertFalse(K._after_hours_slot(_office(day_end="19:00"), dt.datetime(2026, 9, 22, 21, 5)))

    def test_past_the_slots_grace_is_not(self):
        self.assertFalse(K._after_hours_slot(_office(), dt.datetime(2026, 9, 22, 21, 50)))

    def test_sunday_never(self):
        self.assertFalse(K._after_hours_slot(_office(), dt.datetime(2026, 9, 27, 21, 5)))


if __name__ == "__main__":
    unittest.main()
