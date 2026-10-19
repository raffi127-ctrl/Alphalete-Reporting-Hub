import datetime as dt
import unittest

from automations.first_round_scorecards import board

W1, W2, W3 = dt.date(2026, 10, 5), dt.date(2026, 10, 12), dt.date(2026, 10, 19)


class WowTest(unittest.TestCase):
    def weeks(self):
        return {
            W1: {"Ana": {"office": "Raf", "avg": 60, "n": 4},
                 "Iva": {"office": "Nii", "avg": 40, "n": 2},
                 "ZOOM 12": {"office": "", "avg": 90, "n": 1},
                 "TEAM": {"office": "", "avg": 55, "n": 7}},
            W2: {"Ana": {"office": "Raf", "avg": 50, "n": 2},
                 "Eva": {"office": "Nii", "avg": 70, "n": 3},
                 "Iva": {"office": "Nii", "avg": 50, "n": 1}},
            W3: {"Eva": {"office": "Nii", "avg": 80, "n": 1}},
        }

    def test_change_is_vs_her_previous_week_with_a_score(self):
        shown, lines, team = board.wow_lines(self.weeks())
        self.assertEqual(shown, [W1, W2, W3])
        by = {p["name"]: p for p in lines}
        self.assertEqual(by["Ana"]["avgs"], [60, 50, None])
        self.assertEqual(by["Ana"]["change"], -10)          # no score this week: last two she has
        self.assertEqual(by["Eva"]["change"], 10)
        self.assertEqual(team, [55, None, None])

    def test_same_person_yes_joins_weighted(self):
        _, lines, _ = board.wow_lines(self.weeks(), {"Iva": "Eva"})
        by = {p["name"]: p for p in lines}
        self.assertNotIn("Iva", by)
        self.assertEqual(by["Eva"]["avgs"], [40, 65, 80])   # (70*3 + 50*1) / 4
        self.assertEqual(by["Eva"]["n"], 7)

    def test_order_best_latest_first_zooms_last(self):
        _, lines, _ = board.wow_lines(self.weeks())
        self.assertEqual([p["name"] for p in lines], ["Eva", "Ana", "Iva", "ZOOM 12"])

    def test_one_off_names_below_regulars(self):
        w = self.weeks()
        w[W3]["Evaa"] = {"office": "Nii", "avg": 100, "n": 1}
        _, lines, _ = board.wow_lines(w)
        self.assertEqual([p["name"] for p in lines][:3], ["Eva", "Ana", "Iva"])
        self.assertEqual(lines[3]["name"], "Evaa")

    def test_only_last_weeks(self):
        shown, _, _ = board.wow_lines(self.weeks(), last=2)
        self.assertEqual(shown, [W2, W3])

    def test_values_layout(self):
        grid = board.wow_values(*board.wow_lines(self.weeks()))
        self.assertEqual(grid[2][3:6], ["WE 10.11", "WE 10.18", "WE 10.25"])
        self.assertEqual(grid[3][:2], [1, "Eva"])
        self.assertEqual(grid[3][6], "▲ +10")
        self.assertEqual(grid[4][6], "▼ -10")
        self.assertEqual(grid[-1][1], "TEAM")


if __name__ == "__main__":
    unittest.main()
