import datetime as dt
import unittest

from automations.lineup_post import run as R

GRID = [
    ["", "Saturday"],
    ["#", "Car Ride Leader #1", "Car Ride #2", "Car Ride #3", "Car Ride #4", "Car Ride #5", "New T?"],
    ["1", "Jordan Castillo", "Ivan Munoz", "", "", "", "x"],
    ["2", "", "", "", "", ""],
    ["3", "Rhea McKee ", "Jesus  Galvan", "", "", "Auryn Deter"],
    ["", "", "", "", "", "", "", "Mainly Fiber Doors need updated"],
    ["", "Rep names from \nSales Board", "FFP"],
]


class LineupTest(unittest.TestCase):
    def test_box_found_by_header_and_empty_rows_skipped(self):
        hdr, last_col, rows = R.find_box(GRID)
        self.assertEqual((hdr, last_col), (2, 6))
        self.assertEqual([r for r, _, _ in rows], [3, 5])
        self.assertEqual(rows[1][2], ["Rhea McKee", "Jesus Galvan", "Auryn Deter"])

    def test_struck_names_dropped_from_text(self):
        _, _, rows = R.find_box(GRID, struck={(3, 3)})
        txt = R.names_text(rows, dt.date(2026, 10, 22))
        self.assertIn("1. Jordan Castillo\n", txt)
        self.assertNotIn("Ivan", txt)

    def test_tab_is_this_weeks_sunday(self):
        self.assertEqual(R.tab_name(dt.date(2026, 10, 22)), "Line Up WE 10.25")
        self.assertEqual(R.tab_name(dt.date(2026, 10, 25)), "Line Up WE 10.25")


if __name__ == "__main__":
    unittest.main()
