"""python -m unittest automations.production_breakdown.test_push_picture

2026-09-28: a longer Production Breakdown wrote over the weekly knocks picture
(Michael Murphy, Nuri Burgos). It now inserts blank rows above the picture."""
import unittest

from automations.production_breakdown.fill import rows_to_push


def _col_a(marker_row, n=200):
    a = [""] * n
    if marker_row:
        a[marker_row - 1] = "WEEKLY KNOCKS BOARD"
    return a


class PushPictureTest(unittest.TestCase):
    def test_longer_week_pushes_the_picture_down(self):
        # chart ended on 145, picture on 148 (2 blank rows); now ends on 149
        self.assertEqual(rows_to_push(_col_a(148), 145, 149), (148, 4))

    def test_shorter_or_same_week_inserts_nothing(self):
        self.assertEqual(rows_to_push(_col_a(148), 145, 145), (148, 0))
        self.assertEqual(rows_to_push(_col_a(148), 145, 140), (148, 0))

    def test_no_picture_or_picture_already_inside_the_chart(self):
        self.assertEqual(rows_to_push(_col_a(None), 145, 160), (None, 0))
        self.assertEqual(rows_to_push(_col_a(148), 149, 160), (148, 0))


if __name__ == "__main__":
    unittest.main()
