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

    def test_text_is_only_the_leaders_one_per_line(self):
        _, _, rows = R.find_box(GRID)
        self.assertEqual(R.names_text(rows), "Jordan Castillo\nRhea McKee")

    def test_crossed_out_leader_gives_way_to_next_name_on_the_row(self):
        _, _, rows = R.find_box(GRID, struck={(3, 2)})
        self.assertEqual(R.names_text(rows), "Ivan Munoz\nRhea McKee")

    def test_row_with_everyone_crossed_out_is_left_out(self):
        _, _, rows = R.find_box(GRID, struck={(3, 2), (3, 3)})
        self.assertEqual(R.names_text(rows), "Rhea McKee")

    def test_message_has_the_reminder_on_top_then_the_leaders(self):
        _, _, rows = R.find_box(GRID)
        msg = R.names_message(rows)
        self.assertTrue(msg.startswith("Please talk to everyone in you car ride"))
        self.assertTrue(msg.endswith("AD = Add doors\n\n\n\nJordan Castillo\nRhea McKee"))

    def test_reminder_uses_real_emojis_for_imessage(self):
        self.assertIn("✅ = You and your car ride", R.NAMES_REMINDER)
        self.assertIn("❌ = You want new territory", R.NAMES_REMINDER)
        self.assertNotIn(":white_check_mark:", R.NAMES_REMINDER)

    def test_reminder_alone_never_goes_out(self):
        _, _, rows = R.find_box(GRID, struck={(3, 2), (3, 3), (5, 2), (5, 3), (5, 6)})
        self.assertEqual(R.names_message(rows), "")

    def test_tab_is_this_weeks_sunday(self):
        self.assertEqual(R.tab_name(dt.date(2026, 10, 22)), "Line Up WE 10.25")
        self.assertEqual(R.tab_name(dt.date(2026, 10, 25)), "Line Up WE 10.25")


if __name__ == "__main__":
    unittest.main()
