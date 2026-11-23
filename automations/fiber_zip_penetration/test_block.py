import unittest

from automations.fiber_zip_penetration import block


DATA = {
    "75001": {"leads": 100.0, "pct": 0.012, "sales": 1.0, "needed": 1.0, "expected": 2.0, "days": 5.0},
    "75002": {"leads": 300.0, "pct": 0.02, "sales": 6.0, "needed": 0.0, "expected": 6.0, "days": 1.0},
}


class BlockTest(unittest.TestCase):
    def test_grid_sorted_with_total(self):
        g, total = block.grid("Cody Cannon", DATA, 10, 0)
        self.assertEqual(g[0][0], block.title("Cody Cannon"))
        self.assertEqual(g[1], block.HEADERS)
        self.assertEqual([g[2][0], g[3][0]], ["75002", "75001"])    # most leads first
        self.assertEqual(g[2][2], "2.00%")
        self.assertEqual(g[2][3], "=L3*1%/17")                     # leads column = col+1 = L
        self.assertEqual(total, 4)
        self.assertEqual(g[4][0], "Total")
        self.assertEqual(g[4][1], "=SUM(L3:L4)")
        self.assertEqual(g[4][7], "=MIN(R3:R4)")
        self.assertEqual(g[4][2], "1.75%")                         # 7 sales / 400 leads
        self.assertTrue(all(len(r) == block.WIDTH for r in g))

    def test_grid_pads_old_rows(self):
        g, _ = block.grid("X", DATA, 0, 9)
        self.assertEqual(len(g), 9)
        self.assertEqual(g[-1], [""] * block.WIDTH)

    def test_find_and_last_used(self):
        vals = [["a", "", "", block.title("Cody Cannon")], ["b", "c"]]
        self.assertEqual(block.find_block(vals, "Cody Cannon"), 3)
        self.assertIsNone(block.find_block(vals, "Jacob Dover"))
        self.assertEqual(block.last_used_col([["a", ""], ["", "", ""]], [["", "", "=1"]]), 2)

    def test_rows_in_use(self):
        vals = [["", "", "t"], ["", "", "h"], ["x"], ["", "", "", "z"]]
        self.assertEqual(block.block_rows_in_use(vals, 2), 4)

    def test_outside_changed(self):
        before = [["a", "b", ""], ["c", "", ""]]
        after = [["a", "b", "NEW"], ["c", "", "x"]]
        self.assertEqual(block.outside_changed(before, after, 2), [])
        after2 = [["a", "B", "NEW"]]
        self.assertEqual(len(block.outside_changed(before, after2, 2)), 2)


if __name__ == "__main__":
    unittest.main()
