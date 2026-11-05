import datetime as dt
import unittest

from automations.stations_post import run as R

# Same shape as the live tab on 2026-11-05: a labeled block, a station with no
# names, titled rooms with no names past it, then an unrelated table on the
# right sharing the same rows, and reference lists underneath.
GRID = [
    ["", "Trainers", "Week 1's", "", "Late Obj", "", "", "", "Leaders Meetings"],
    ["Where? ", "Fishbowl", "Fishbowl", "Fishbowl", "Fishbowl", "Chicago", "CF Room", "", "Monday"],
    ["Timing", "10:30", "10:30", "10:30", "10:30", "10:30", "10:30", "", "Tuesday"],
    ["Running it ", "", "", "", "", "", "", "", "Wednesday"],
    ["1", "Ana", "Bryson", "", "", "", "", "", "Thursday"],
    ["3", "", "", "", "", "", "", "", "WK2"],
    ["4", "Willie", "", "", "", "", "", "", ""],
    ["5", "", "", "", "", "", "", "", ""],
    ["", "Shift+Command+V = Paste without Formula"],
    ["", "Rep names from \nSales Board", "FFP", "New Starts", "Roadtrips"],
    ["", "Andrew", "", "Laiza", "Aniyah"],
]


class FindBoxTest(unittest.TestCase):
    def test_stops_at_last_name_not_at_titles_or_side_tables(self):
        self.assertEqual(R.find_box(GRID), (7, 3))

    def test_empty_numbered_row_inside_the_block_stays(self):
        grid = [list(r) for r in GRID]
        grid[7][1] = "Jacari"      # row 8 gets a name; row 6 is empty in the middle
        self.assertEqual(R.find_box(grid), (8, 3))

    def test_leader_with_no_reps_keeps_the_station(self):
        grid = [list(r) for r in GRID]
        grid[3][4] = "Aundre"      # 'Running it' in col E
        self.assertEqual(R.find_box(grid), (7, 5))

    def test_road_trip_station_is_cut_leader_included(self):
        grid = [list(r) for r in GRID]
        grid[3][4] = "Lakeaih"     # leader of the road-trip station
        grid[4][4] = "aniyah "     # on the Roadtrips list, spacing/case aside
        self.assertEqual(R.find_box(grid), (7, 3))

    def test_one_office_rep_keeps_the_station(self):
        grid = [list(r) for r in GRID]
        grid[4][4] = "Aniyah"
        grid[5][4] = "Wendy"
        self.assertEqual(R.find_box(grid), (7, 5))

    def test_no_roadtrips_list_raises_instead_of_leaking(self):
        grid = [list(r) for r in GRID]
        grid[9] = ["", "Rep names", "FFP", "New Starts", "Off"]
        with self.assertRaises(SystemExit) as e:
            R.find_box(grid)
        self.assertIn("Roadtrips", str(e.exception))

    def test_no_rep_names_never_posts(self):
        grid = ([list(r) for r in GRID[:4]] + [["1", "", ""], ["3", "", ""]]
                + [["", "Roadtrips"], ["", "Aniyah"]])
        grid[3][1] = "Leader Only"
        with self.assertRaises(SystemExit) as e:
            R.find_box(grid)
        self.assertIn("no rep names", str(e.exception))

    def test_template_change_raises_instead_of_guessing(self):
        with self.assertRaises(SystemExit):
            R.find_box([r for r in GRID if r[0] != "Where? "])

    def test_caption(self):
        self.assertEqual(R.caption(dt.date(2026, 11, 5)), "Stations - Thursday 11/5")


if __name__ == "__main__":
    unittest.main()
