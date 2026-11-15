"""Pure: one card, several clock times. Nothing runs."""
import datetime as dt
import unittest

from automations.card_scheduler import run as R

MON = dt.datetime(2026, 11, 16)


def card(**sched):
    base = {"frequency": "weekly", "weekdays": [0, 1, 2, 3, 4, 5]}
    base.update(sched)
    return {"id": "c", "module": "m", "schedule": base}


class Times(unittest.TestCase):
    def test_single_time_unchanged(self):
        c = card(time="8:00 AM")
        self.assertEqual(R._due_slot(c, MON.replace(hour=8, minute=5))[0], "8:00 AM")
        self.assertIsNone(R._due_slot(c, MON.replace(hour=9))[0])
        self.assertEqual(R._ran_key(c, "8:00 AM"), "c")
        self.assertTrue(R._due(c, MON.replace(hour=8, minute=5))[0])

    def test_each_time_fires_once_under_its_own_key(self):
        c = card(times=["6:00 AM", "2:45 PM"])
        self.assertEqual(R._due_slot(c, MON.replace(hour=6, minute=10))[0], "6:00 AM")
        self.assertEqual(R._due_slot(c, MON.replace(hour=14, minute=50))[0], "2:45 PM")
        self.assertIsNone(R._due_slot(c, MON.replace(hour=10))[0])
        self.assertEqual(R._ran_key(c, "2:45 PM"), "c@2:45 PM")

    def test_weekday_still_gates(self):
        c = card(times=["6:00 AM"])
        self.assertIsNone(R._due_slot(c, (MON - dt.timedelta(days=1)).replace(hour=6, minute=5))[0])


if __name__ == "__main__":
    unittest.main()
