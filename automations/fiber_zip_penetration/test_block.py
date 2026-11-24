import unittest

from automations.fiber_zip_penetration import block


DATA = {
    "75001": {"leads": 100.0, "pct": 0.012, "sales": 1.0, "needed": 1.0, "expected": 2.0,
              "days": 5.0, "state": "TX"},
    "75002": {"leads": 300.0, "pct": 0.02, "sales": 6.0, "needed": 0.0, "expected": 6.0,
              "days": 1.0, "state": "TX"},
}


class BlockTest(unittest.TestCase):
    def test_grid_sorted_with_total(self):
        g, total = block.grid("Cody Cannon", DATA, 10, 0)
        self.assertEqual(g[0][0], block.title("Cody Cannon"))
        self.assertEqual(g[1], block.HEADERS)
        self.assertEqual(g[1][:2], ["City, State", "Zip Code"])     # city in front of zip
        self.assertEqual([g[2][1], g[3][1]], ["75002", "75001"])    # most leads first
        self.assertEqual(g[2][0], "Allen, TX")
        self.assertEqual(g[2][3], "2.00%")
        self.assertEqual(g[2][4], "=M3*1%/17")                     # leads column = col+2 = M
        self.assertEqual(total, 4)
        self.assertEqual(g[4][0], "Total")
        self.assertEqual(g[4][2], "=SUM(M3:M4)")
        self.assertEqual(g[4][8], "=MIN(S3:S4)")
        self.assertEqual(g[4][3], "1.75%")                         # 7 sales / 400 leads
        self.assertTrue(all(len(r) == block.WIDTH for r in g))

    def test_city_state(self):
        self.assertEqual(block.city_state("48066"), "Roseville, MI")
        self.assertEqual(block.city_state("77049"), "Houston, TX")
        self.assertEqual(block.city_state("00000", "LA"), "LA")    # unknown zip: state only
        self.assertEqual(block.city_state("00000"), "")

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

    def test_place_new_block_leaves_gap(self):
        vals = [["a", "b"], ["c"]]
        self.assertEqual(block.place(vals, vals, "Cody Cannon")["col"], 1 + 1 + block.GAP)

    def _old_block(self, at, owner, board_cols=2):
        """Board in A..(board_cols), old 8-wide block (no City) starting at `at`."""
        r0 = ["x"] * board_cols + [""] * (at - board_cols) + [block.title(owner)] + [""] * 7
        r1 = ["x"] * board_cols + [""] * (at - board_cols) + ["h"] * 8
        r2 = ["x"] * board_cols + [""] * (at - board_cols) + ["1"] * 8
        return [r0, r1, r2]

    def test_place_moves_a_block_that_is_too_close(self):
        vals = self._old_block(3, "Cody Cannon")             # board A:B, 1 blank col, block D
        p = block.place(vals, vals, "Cody Cannon")
        self.assertEqual((p["col"], p["old_col"], p["old_width"], p["old_rows"]),
                         (2 + block.GAP, 3, 8, 3))

    def test_place_keeps_a_block_already_spaced(self):
        vals = self._old_block(2 + block.GAP, "Cody Cannon")
        p = block.place(vals, vals, "Cody Cannon")
        self.assertEqual(p["col"], p["old_col"])

    def test_place_jumps_over_the_next_owners_block(self):
        # Hammad's old block at D, Salik's at M (shared Line Up): moving Hammad
        # right would land on Salik -> Hammad goes to the far right instead.
        vals = self._old_block(3, "Hammad Haque")
        for r, x in zip(vals, [block.title("Salik Mallick"), "h", "1"]):
            r += [""] + [x] + [x if x != block.title("Salik Mallick") else ""] * 7
        p = block.place(vals, vals, "Hammad Haque")
        self.assertEqual(p["old_col"], 3)
        self.assertEqual(p["col"], 12 + 7 + 1 + block.GAP)

    def test_cf_delete_only_rules_inside_block(self):
        existing = [{"ranges": [{"startColumnIndex": 0, "endColumnIndex": 40}]},   # owner's
                    {"ranges": [{"startColumnIndex": 13, "endColumnIndex": 14}]}]  # Lucy's
        reqs = block.cf_delete_requests(7, existing, range(10, 19))
        self.assertEqual([r["deleteConditionalFormatRule"]["index"] for r in reqs], [1])

    def test_format_has_borders_and_merged_title(self):
        reqs = block.format_requests(7, 10, 5, old_rows=9)
        kinds = [next(iter(r)) for r in reqs]
        self.assertIn("mergeCells", kinds)
        self.assertIn("updateBorders", kinds)
        merge = next(r["mergeCells"]["range"] for r in reqs if "mergeCells" in r)
        self.assertEqual((merge["startColumnIndex"], merge["endColumnIndex"]), (10, 19))
        self.assertEqual(reqs[-1]["updateCells"]["range"]["startRowIndex"], 6)  # leftovers reset

    def test_outside_changed(self):
        before = [["a", "b", ""], ["c", "", ""]]
        after = [["a", "b", "NEW"], ["c", "", "x"]]
        self.assertEqual(block.outside_changed(before, after, 2), [])
        after2 = [["a", "B", "NEW"]]
        self.assertEqual(len(block.outside_changed(before, after2, 2)), 2)
        self.assertEqual(len(block.outside_changed(before, after2, 2, range(1, 2))), 1)  # B1 skipped


if __name__ == "__main__":
    unittest.main()
