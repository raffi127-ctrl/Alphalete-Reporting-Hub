"""Borders on the NDS CHURN tab's lists (Carlos 2026-11-14)."""
import unittest

from automations.nds_churn import sheet as S


class Borders(unittest.TestCase):
    def test_requests(self):
        reqs = S.border_requests(7, n_rows=12, cap=60, rep_a1="P15:Q34")
        self.assertEqual(len(reqs), 3)
        lst = reqs[0]["updateBorders"]
        self.assertEqual((lst["range"]["startRowIndex"], lst["range"]["endRowIndex"]), (14, 27))   # row 15 + 12 rows
        self.assertEqual((lst["range"]["startColumnIndex"], lst["range"]["endColumnIndex"]), (0, 14))
        self.assertEqual(lst["innerHorizontal"]["style"], "SOLID")
        clr = reqs[1]["updateBorders"]
        self.assertEqual((clr["range"]["startRowIndex"], clr["range"]["endRowIndex"]), (27, 60))
        self.assertEqual(clr["top"]["style"], "NONE")
        rep = reqs[2]["updateBorders"]["range"]
        self.assertEqual((rep["startRowIndex"], rep["endRowIndex"], rep["startColumnIndex"], rep["endColumnIndex"]),
                         (14, 34, 15, 17))

    def test_no_rep_list_and_full_spill(self):
        reqs = S.border_requests(7, n_rows=45, cap=60, rep_a1=None)
        self.assertEqual(len(reqs), 1)                 # spill reaches the cap: nothing to clear
        reqs = S.border_requests(7, n_rows=40, cap=60, rep_a1=None)
        self.assertEqual(len(reqs), 2)
        reqs = S.border_requests(7, n_rows=0, cap=60, rep_a1=None)
        self.assertEqual(reqs[0]["updateBorders"]["range"]["endRowIndex"], 15)   # header only
        self.assertEqual(S._a1_span_to_range("AB3:AC10", 1),
                         {"sheetId": 1, "startRowIndex": 2, "endRowIndex": 10,
                          "startColumnIndex": 27, "endColumnIndex": 29})


if __name__ == "__main__":
    unittest.main()
