"""Block 3 ('All Units - All Campaigns') is found whichever column holds its header.

2026-09-15: the header became a merged A:B cell, so Sheets reports its text in
col A and the col-B-only lookup raised — the whole fill died the first morning
a new rep (Samuel Acay) had to be added.
"""
import unittest

from automations.all_campaigns_board import roster as rs


def grid(header_col: int):
    hdr = ["", "", "Total for week"]
    hdr[header_col] = rs.RANKING_LABEL
    return [
        ["All Units", "", "Monday"],
        ["", "", ""],
        hdr,                                            # row 3
        ["", "", "Total this week"],                    # row 4, sub-header
        ["1", "Jairo Ruiz", "0"],                       # row 5
        ["2", "Colten Wright", "0"],                    # row 6
        ["", "", "0"],                                  # row 7, totals
    ]


class FindRankingBlock(unittest.TestCase):
    def test_header_in_col_a_merged_cell(self):
        b = rs.find_ranking_block(grid(0))
        self.assertEqual(b, {"header_row": 3, "data_rows": [5, 6]})

    def test_header_in_col_b_still_works(self):
        b = rs.find_ranking_block(grid(1))
        self.assertEqual(b, {"header_row": 3, "data_rows": [5, 6]})

    def test_missing_header_still_raises(self):
        g = grid(0)
        g[2][0] = "Something else"
        with self.assertRaises(ValueError):
            rs.find_ranking_block(g)

    def test_new_rep_goes_in_at_the_last_data_row(self):
        self.assertEqual(rs._insert_position(rs.find_ranking_block(grid(0))["data_rows"]), 6)


if __name__ == "__main__":
    unittest.main()
