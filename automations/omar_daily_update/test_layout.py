"""python -m unittest automations.omar_daily_update.test_layout"""
import unittest

from automations.omar_daily_update import layout as OL

# Row 1 of Omar's 'Daily Update' tab as read 2026-10-26; K onward is the
# MONTHLY TOTALS block (L1 'MONTHLY TOTALS').
HEADER = ["Date", "1st round Interviewer", "2nd Round Interviewer", "First Name",
          "Last Name", "Follow Up Status", "BOB \nDate", "Phone Number",
          "SHOWED TO DAY 1", "", "", "MONTHLY TOTALS"]


class Resolve(unittest.TestCase):
    def test_omar_header(self):
        lay = OL.resolve(HEADER)
        self.assertEqual(lay, {"date": 0, "int1": 1, "int2": 2, "first": 3,
                               "last": 4, "status": 5, "bob_date": 6,
                               "phone": 7, "day1": 8})

    def test_stops_at_first_blank(self):
        self.assertNotIn("email", OL.resolve(HEADER + ["Email"]))

    def test_missing_column_raises(self):
        with self.assertRaises(ValueError):
            OL.resolve(HEADER[:5])

    def test_never_writes_showed_to_day_1(self):
        self.assertNotIn("day1", OL.WRITE_KEYS)


if __name__ == "__main__":
    unittest.main()
