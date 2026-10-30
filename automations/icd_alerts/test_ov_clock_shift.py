"""OwnerVille's clock is the login's; the board reads it on the office's."""
import datetime as dt
import unittest

from automations.icd_alerts import knocks_post as K, offices as O


class _Office:
    key = "omar"
    timezone = "America/New_York"


class _Central:
    key = "hasani"
    timezone = "America/Chicago"


class OwnerVilleClockShift(unittest.TestCase):
    def test_omar_reads_central_as_eastern(self):
        now = dt.datetime(2026, 10, 30, 15, 25)
        self.assertEqual(O.ov_clock_shift_minutes(_Office(), now), 60)
        raw = [{"rep": "Aaron Dudley", "first knock": "12:50 PM", "last knock": "2:22 PM"}]
        tr = [{"name": "Aaron Dudley", "firstKnockDate": "12:50 PM", "lastKnockDate": "2:22 PM",
               "firstKnockTimestamp": "2026-10-30T12:50:10", "lastKnockTimestamp": "2026-10-30T14:22:05",
               "totalGapMinutes": 16, "minutesSinceLastKnock": 3}]
        raw, tr = K.shift_ov_clock(_Office(), raw, tr, now)
        self.assertEqual(raw[0]["first knock"], "1:50 PM")
        self.assertEqual(raw[0]["last knock"], "3:22 PM")
        self.assertEqual(tr[0]["lastKnockTimestamp"], "2026-10-30T15:22:05")
        self.assertEqual(tr[0]["totalGapMinutes"], 16)        # a duration, untouched
        self.assertEqual(tr[0]["minutesSinceLastKnock"], 3)   # relative, untouched

    def test_an_office_on_its_own_clock_is_untouched(self):
        now = dt.datetime(2026, 10, 30, 15, 25)
        self.assertEqual(O.ov_clock_shift_minutes(_Central(), now), 0)
        raw = [{"rep": "A", "last knock": "2:22 PM"}]
        raw, tr = K.shift_ov_clock(_Central(), raw, [], now)
        self.assertEqual(raw[0]["last knock"], "2:22 PM")

    def test_gap_minutes_follow_the_shift(self):
        now = dt.datetime(2026, 10, 30, 15, 25)
        self.assertEqual(K._minutes_since("3:22 PM", now), 3)


if __name__ == "__main__":
    unittest.main()
