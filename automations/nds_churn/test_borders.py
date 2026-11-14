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


class ActivationListTotal(unittest.TestCase):
    """2026-11-14: the office 0-30 activation rate tops the per-rep list."""

    def test_rows_and_bands(self):
        from automations.vantura_churn import fill as VF
        office = {"0-30": {"activated": 50, "sold": 100, "rate": 0.5}, "31-60": {"activated": 0, "sold": 0, "rate": None}}
        reps = {"Ana": {"0-30": {"activated": 9, "sold": 10, "rate": 0.9}, "31-60": {"rate": None}},
                "Ben": {"0-30": {"activated": 1, "sold": 4, "rate": 0.25}, "31-60": {"rate": None}},
                "Cy": {"0-30": {"activated": 0, "sold": 0, "rate": None}, "31-60": {"rate": None}}}
        rows, ranked, bands = VF.activation_list_rows(office, reps, "OFFICE TOTAL (all reps)")
        self.assertEqual(rows, [["Rep Name", "0-30 Day Activation Rate"], ["OFFICE TOTAL (all reps)", 0.5],
                                ["Ana", 0.9], ["Ben", 0.25]])
        self.assertEqual(bands, [0.5, 0.9, 0.25])
        self.assertEqual([r for r, _v in ranked], ["Ana", "Ben"])          # Cy: no 0-30 sales, dropped
        rows2, _r, bands2 = VF.activation_list_rows(office, reps)         # B2B: no total row
        self.assertEqual(rows2[1][0], "Ana")
        self.assertEqual(bands2, [0.9, 0.25])

