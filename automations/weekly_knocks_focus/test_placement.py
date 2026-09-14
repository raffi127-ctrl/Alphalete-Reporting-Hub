"""python -m unittest automations.weekly_knocks_focus.test_placement"""
import unittest

from automations.weekly_knocks_focus import placement as P

# 'Kash Rai - Test Eve' geometry, measured 2026-09-14: A 120px, B 279px, the
# week columns 75px, rows 21px; A:B frozen; last used row 157.
COL_PX = [120, 279] + [75] * 130
ROW_PX = [21] * 1069


class PlacementTest(unittest.TestCase):
    def test_block_is_wide_enough_and_keeps_the_aspect(self):
        # A 2:1 board shown 1200px wide needs 600px of height.
        end_col, end_row = P.block(COL_PX, ROW_PX, 3, 160, 2400, 1200)
        self.assertEqual(end_col, 3 + 16 - 1)          # 16 x 75px = 1200
        self.assertEqual(end_row, 160 + 29 - 1)        # 29 x 21px = 609 >= 600

    def test_missing_pixel_sizes_fall_back_to_defaults(self):
        end_col, end_row = P.block([], [], 3, 1, 1000, 100)
        self.assertEqual(end_col, 3 + 12 - 1)          # 12 x 100px = 1200
        self.assertEqual(end_row, 1 + 6 - 1)           # 6 x 21px = 126 >= 120

    def test_marker_found_by_label_anywhere_in_column_a(self):
        col_a = ["OFFICE GOALS", "", "  weekly knocks   board ", "x"]
        self.assertEqual(P.find_marker(col_a), 3)
        self.assertIsNone(P.find_marker(["OFFICE GOALS", "OPT"]))

    def test_last_used_row_looks_at_every_column(self):
        values = [["a"], [""], ["", "", "", "z"], ["", ""]]
        self.assertEqual(P.last_used_row(values), 3)
        self.assertEqual(P.last_used_row([]), 0)

    def test_area_is_empty_refuses_a_block_over_data(self):
        values = [["", "", ""], ["", "", "5"], ["", "", ""]]
        self.assertFalse(P.area_is_empty(values, 1, 3, 2, 3))
        self.assertTrue(P.area_is_empty(values, 1, 3, 1, 2))
        self.assertTrue(P.area_is_empty(values, 5, 9, 1, 9))   # past the data

    def test_merges_at_matches_top_left_only(self):
        merges = [
            {"sheetId": 7, "startRowIndex": 159, "startColumnIndex": 2,
             "endRowIndex": 190, "endColumnIndex": 18},
            {"sheetId": 7, "startRowIndex": 10, "startColumnIndex": 2},
            {"sheetId": 8, "startRowIndex": 159, "startColumnIndex": 2},
        ]
        self.assertEqual(len(P.merges_at(merges, 7, 160, 3)), 1)


if __name__ == "__main__":
    unittest.main()
