"""Raf 2026-10-19: "in my A players chat at 9:00 CEN can I get a text broken
down by each team, of every rep that doesn't have 125 doors knocked for the
day". Once a day, 9pm weekdays / 8pm Saturday (the window's last pull)."""
import datetime as dt
import unittest
from unittest import mock

from automations.gap_alerts import config as C
from automations.gap_alerts import run as R


class _Book:
    def __init__(self, m):
        self.m = m

    def team_for(self, rep):
        return self.m.get(rep, "")


ROWS = [{"Rep": "Ana Diaz", "Total Knocks": "140"},
        {"Rep": "Bo Lee", "Total Knocks": "98"},
        {"Rep": "Cy Ray", "Total Knocks": "124"},
        {"Rep": "Di Fox", "Total Knocks": "150"},
        {"Rep": "Ed Kim", "Total Knocks": "60"}]
BOOK = _Book({"Ana Diaz": "Wolves", "Bo Lee": "Wolves", "Cy Ray": "Wolves",
              "Di Fox": "Eagles"})
DAY = dt.date(2026, 10, 19)


class FloorText(unittest.TestCase):
    def test_by_team_fewest_first(self):
        t = R.floor_text(ROWS, BOOK, 125, DAY)
        self.assertIn("Under 125 doors today — Mon 10/19", t)
        self.assertIn("Eagles — ✅ all 1 at 125+", t)
        self.assertIn("Wolves — 2 of 3 under\n• Bo Lee — 98\n• Cy Ray — 124", t)
        self.assertIn("Unassigned — 1 of 1 under\n• Ed Kim — 60", t)
        self.assertNotIn("Ana Diaz", t)
        self.assertTrue(t.endswith("Total: 3 of 5 reps under 125"))
        # Unassigned draws last
        self.assertLess(t.index("Wolves"), t.index("Unassigned"))

    def test_exactly_125_is_not_under(self):
        t = R.floor_text([{"Rep": "X Y", "Total Knocks": "125"}], None, 125, DAY)
        self.assertIn("All reps — ✅ all 1 at 125+", t)


class FloorDue(unittest.TestCase):
    CFG = dict(C.RAF)

    def _due(self, when, sent=None):
        st = {"_floor_sent": {"rafael": sent}} if sent else {}
        with mock.patch.object(R, "_state", return_value=st):
            return R._floor_due(self.CFG, when)

    def test_weekday_from_9pm(self):
        self.assertFalse(self._due(dt.datetime(2026, 10, 19, 20, 45)))
        self.assertTrue(self._due(dt.datetime(2026, 10, 19, 21, 0)))
        self.assertTrue(self._due(dt.datetime(2026, 10, 19, 21, 30)))

    def test_once_a_day(self):
        self.assertFalse(self._due(dt.datetime(2026, 10, 19, 21, 30), "2026-10-19"))
        self.assertTrue(self._due(dt.datetime(2026, 10, 20, 21, 0), "2026-10-19"))

    def test_saturday_8pm_sunday_never(self):
        self.assertFalse(self._due(dt.datetime(2026, 10, 24, 19, 45)))
        self.assertTrue(self._due(dt.datetime(2026, 10, 24, 20, 0)))
        self.assertFalse(self._due(dt.datetime(2026, 10, 25, 21, 0)))

    def test_raf_asked_for_it(self):
        spec = C.RAF["floor_text"]
        self.assertEqual((spec["min_knocks"], spec["at"], spec["group"]),
                         (125, "21:00", "Knocking Chat A-Players"))


if __name__ == "__main__":
    unittest.main()
