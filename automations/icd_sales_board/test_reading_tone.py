"""A relay that has gone quiet in selling hours goes bright red.

Megan 2026-10-06: "if the last read time is over 2 hours (if during posting
times) then it should go bright red so we know it's down". Ryan Mcspadden
was the first one it caught -- last reading 2026-10-05 20:10, found on the
Tuesday afternoon, about 21 hours cold.

Pure function, no network: every clock here is passed in.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.icd_sales_board import enrollment as EN


class _Office:
    """Only the fields reading_tone looks at."""

    def __init__(self, tz="America/Chicago", day="13:00", end="20:30",
                 saturday=True, sat_start="11:00", sat_end="17:00"):
        self.timezone, self.day_start, self.day_end = tz, day, end
        self.saturday, self.sat_start, self.sat_end = saturday, sat_start, sat_end


TUE_AFTERNOON = dt.datetime(2026, 10, 6, 17, 0)     # a Tuesday, mid-shift
TUE_LATE = dt.datetime(2026, 10, 6, 23, 30)         # after close
SUNDAY = dt.datetime(2026, 10, 4, 15, 0)
SATURDAY = dt.datetime(2026, 10, 3, 15, 0)


class InSellingHours(unittest.TestCase):

    def test_a_fresh_reading_is_good(self):
        self.assertEqual(
            EN.reading_tone("2026-10-06 16:50", _Office(), now=TUE_AFTERNOON),
            "good")

    def test_just_under_two_hours_is_still_good(self):
        self.assertEqual(
            EN.reading_tone("2026-10-06 15:05", _Office(), now=TUE_AFTERNOON),
            "good")

    def test_over_two_hours_is_down(self):
        self.assertEqual(
            EN.reading_tone("2026-10-06 14:30", _Office(), now=TUE_AFTERNOON),
            "down")

    def test_ryans_actual_reading(self):
        """The one this was built for: yesterday evening, found Tuesday."""
        self.assertEqual(
            EN.reading_tone("2026-10-05 20:10", _Office(), now=TUE_AFTERNOON),
            "down")


class OutsideSellingHours(unittest.TestCase):
    """A shut office is quiet on purpose; red every night means nothing."""

    def test_after_close_a_cold_relay_is_not_a_fault(self):
        self.assertEqual(
            EN.reading_tone("2026-10-06 14:30", _Office(), now=TUE_LATE),
            "good")

    def test_sunday_is_never_red(self):
        self.assertEqual(
            EN.reading_tone("2026-10-02 14:30", _Office(), now=SUNDAY),
            "good")

    def test_saturday_uses_its_own_hours(self):
        o = _Office(sat_start="11:00", sat_end="17:00")
        # 14:30 against a 15:00 Saturday clock: half an hour old, inside
        # the 11-5 window, so good. (11:30 would be 3h30 cold -- down.)
        self.assertEqual(EN.reading_tone("2026-10-03 14:30", o, now=SATURDAY),
                         "good")
        self.assertEqual(EN.reading_tone("2026-10-03 09:00", o, now=SATURDAY),
                         "down")

    def test_an_office_shut_on_saturday_is_not_red(self):
        o = _Office(saturday=False)
        self.assertEqual(EN.reading_tone("2026-10-02 09:00", o, now=SATURDAY),
                         "good")


class TheOfficesOwnClock(unittest.TestCase):
    """The claim the whole rule rests on."""

    def test_the_same_stamp_differs_by_timezone(self):
        # 15:30 local. For a Central office it is 90 minutes old at 17:00
        # Central; the stamp an Eastern office wrote at 15:30 ITS time is
        # already 2h30 old when its own clock says 18:00.
        central = EN.reading_tone("2026-10-06 15:30", _Office("America/Chicago"),
                                  now=dt.datetime(2026, 10, 6, 17, 0))
        eastern = EN.reading_tone("2026-10-06 15:30",
                                  _Office("America/New_York"),
                                  now=dt.datetime(2026, 10, 6, 18, 0))
        self.assertEqual(central, "good")
        self.assertEqual(eastern, "down")


class NothingToJudge(unittest.TestCase):

    def test_never_is_left_to_the_caller(self):
        for v in ("", "never", "-", "—", None):
            self.assertEqual(EN.reading_tone(v, _Office(), now=TUE_AFTERNOON),
                             "", repr(v))

    def test_an_unparseable_stamp_does_not_raise(self):
        self.assertEqual(
            EN.reading_tone("yesterday-ish", _Office(), now=TUE_AFTERNOON), "")

    def test_no_office_still_answers(self):
        self.assertIn(EN.reading_tone("2026-10-06 16:50", None,
                                      now=TUE_AFTERNOON), ("good", "down"))


class TheRedIsDistinct(unittest.TestCase):

    def test_down_is_not_the_pale_bad_red(self):
        self.assertIn("down", EN._TONE_CSS)
        self.assertNotEqual(EN._TONE_CSS["down"], EN._TONE_CSS["bad"])
        self.assertIn("#DC2626", EN._TONE_CSS["down"])

    def test_the_marker_is_not_a_public_column(self):
        self.assertNotIn("_reading_tone", EN.SAFE_COLUMNS)
        self.assertNotIn("_reading_tone", EN.ADMIN_EXTRA)


if __name__ == "__main__":
    unittest.main()
