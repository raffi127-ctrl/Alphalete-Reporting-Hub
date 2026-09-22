"""The full-detail knocks reader. No network."""
import datetime as dt
import unittest

from automations.icd_sales_board import knocks_log as K

HDR = ["Date", "Office", "ID", "Rep", "Total Knocks", "Total Talk to",
       "Sale", "Gaps", "First Knock", "Last Knock"]
GRID = [
    HDR,
    # One rep, one day, split across two rows — the shape a second pull makes.
    ["2026-09-21", "Cyrus Wade", "1", "Amarion Hill", "40", "5", "1", "3",
     "8:20 PM", "8:40 PM"],
    ["2026-09-21", "Cyrus Wade", "1", "Amarion Hill", "35", "6", "1", "10",
     "12:53 PM", "6:00 PM"],
    # A rep who never clocked in: Gaps blank, counts real.
    ["2026-09-21", "Cyrus Wade", "2", "Nevin Singleton", "10", "1", "0", "",
     "1:00 PM", "2:00 PM"],
    # Another office, and a day outside the window.
    ["2026-09-21", "Aya Al-Khafaji", "3", "Someone Else", "99", "9", "9", "9",
     "", ""],
    ["2026-09-14", "Cyrus Wade", "1", "Amarion Hill", "77", "7", "7", "7",
     "", ""],
]
DAY = dt.date(2026, 9, 21)


class DetailTests(unittest.TestCase):
    def setUp(self):
        self.d = K.detail_from(GRID, "Cyrus Wade", DAY, DAY)

    def test_only_this_office_and_this_window(self):
        self.assertEqual(sorted(self.d), ["amarion hill", "nevin singleton"])
        self.assertEqual(list(self.d["amarion hill"]), [DAY])

    def test_two_rows_of_one_day_add_up(self):
        cell = self.d["amarion hill"][DAY]
        self.assertEqual(cell["Total Knocks"], 75)
        self.assertEqual(cell["Total Talk to"], 11)
        self.assertEqual(cell["Sale"], 2)

    def test_first_and_last_knock_are_clock_times_not_strings(self):
        # '8:20 PM' sorts before '12:53 PM' as text, which made the earliest
        # knock of a two-row day come out as the latest.
        cell = self.d["amarion hill"][DAY]
        self.assertEqual(cell["First Knock"], "12:53 PM")
        self.assertEqual(cell["Last Knock"], "8:40 PM")

    def test_a_blank_gap_stays_blank(self):
        # 'did not clock in' is not 'stood still for zero minutes'.
        self.assertEqual(self.d["nevin singleton"][DAY]["Gaps"], "")
        self.assertEqual(self.d["amarion hill"][DAY]["Gaps"], 13)

    def test_columns_come_from_the_header(self):
        grid = [HDR + ["Brand New Outcome"],
                ["2026-09-21", "Cyrus Wade", "1", "A", "1", "1", "0", "0",
                 "", "", "4"]]
        cell = K.detail_from(grid, "Cyrus Wade", DAY, DAY)["a"][DAY]
        self.assertEqual(cell["Brand New Outcome"], 4)

    def test_an_office_with_nothing_is_empty_not_an_error(self):
        self.assertEqual(K.detail_from(GRID, "Nobody At All", DAY, DAY), {})
        self.assertEqual(K.detail_from([], "Cyrus Wade", DAY, DAY), {})


if __name__ == "__main__":
    unittest.main()
