"""python -m unittest automations.weekly_knocks_focus.test_placement"""
import unittest

from automations.weekly_knocks_focus import placement as P

# 'Kash Rai - Test Eve' geometry, measured 2026-09-14: A 120px, B 279px, the
# week columns 75px, rows 21px; A:B frozen; 132 columns; WE 9/13 is CP (94).
COL_PX = [120, 279] + [75] * 130
ROW_PX = [21] * 1069
CP = 94


class PlacementTest(unittest.TestCase):
    def test_block_starts_at_the_current_week_and_keeps_the_aspect(self):
        # A 2:1 board shown 1200px wide needs 600px of height.
        end_col, end_row = P.block(COL_PX, ROW_PX, CP, 160, 2400, 1200)
        self.assertEqual(end_col, CP + 16 - 1)         # CP..DE, 16 x 75px
        self.assertEqual(end_row, 160 + 29 - 1)        # 29 x 21px = 609 >= 600

    def test_block_stops_at_the_last_column_and_gets_shorter(self):
        # 3 columns left (130..132): 225px wide -> 112.5px tall at 2:1.
        end_col, end_row = P.block(COL_PX, ROW_PX, 130, 160, 2400, 1200,
                                   max_col=132)
        self.assertEqual(end_col, 132)
        self.assertEqual(end_row, 160 + 6 - 1)         # 6 x 21px = 126 >= 112.5

    def test_missing_pixel_sizes_fall_back_to_defaults(self):
        end_col, end_row = P.block([], [], 3, 1, 1000, 100)
        self.assertEqual(end_col, 3 + 12 - 1)          # 12 x 100px = 1200
        self.assertEqual(end_row, 1 + 6 - 1)           # 6 x 21px = 126 >= 120

    def test_start_column_is_the_week_but_never_frozen(self):
        self.assertEqual(P.start_column(CP, 2), CP)
        self.assertEqual(P.start_column(2, 2), 3)

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

    def test_last_weeks_block_does_not_count_as_data(self):
        # Last week's =IMAGE sits in C1 (row 1, col 3) inside its merge.
        values = [["", "", "=IMAGE(x)"], ["", "", ""]]
        old = [{"sheetId": 7, "startRowIndex": 0, "endRowIndex": 2,
                "startColumnIndex": 2, "endColumnIndex": 4}]
        self.assertFalse(P.area_is_empty(values, 1, 2, 3, 4))
        self.assertTrue(P.area_is_empty(values, 1, 2, 3, 4, ignore=old))

    def test_merges_on_row_finds_last_weeks_block_wherever_it_started(self):
        merges = [
            {"sheetId": 7, "startRowIndex": 159, "startColumnIndex": 2,
             "endRowIndex": 196, "endColumnIndex": 18},     # C160 (old spot)
            {"sheetId": 7, "startRowIndex": 159, "startColumnIndex": 93,
             "endRowIndex": 196, "endColumnIndex": 109},    # CP160
            {"sheetId": 7, "startRowIndex": 159, "startColumnIndex": 0,
             "endRowIndex": 160, "endColumnIndex": 2},      # A:B, frozen area
            {"sheetId": 7, "startRowIndex": 10, "startColumnIndex": 2},
            {"sheetId": 8, "startRowIndex": 159, "startColumnIndex": 2},
        ]
        found = P.merges_on_row(merges, 7, 160, 3)
        self.assertEqual([m["startColumnIndex"] for m in found], [2, 93])


if __name__ == "__main__":
    unittest.main()
