"""The NDS CHURN tab's top block (rows 4-12): the box with Pending as a
column (Carlos 2026-11-17: "the pending orders should be another column not
another row. The order of the columns should be disconnected - activations
- pending") and the tier charts beside it."""
import unittest

from automations.nds_churn import comp
from automations.nds_churn import sheet as S

BOX = {"all_orders": {"act": 249, "disc": 34, "pend": 207},
       "wireless": {"act": 123, "disc": 16, "pend": 139},
       "byod": {"act": 119, "disc": 15, "pend": 66},
       "air": {"act": 7, "disc": 3, "pend": 2},
       "internet": {"act": 2, "disc": 0, "pend": 0}}


def _rate(act, sold):
    return {"activated": act, "sold": sold, "rate": (act / sold) if sold else None}


RATES = {k: {"0-30": _rate(*a), "31-60": _rate(*b)} for k, (a, b) in {
    "all_orders": ((250, 470), (0, 0)), "wireless": ((120, 267), (0, 0)),
    "byod": ((119, 185), (9, 10)), "air": ((7, 9), (0, 0)),
    "internet": ((2, 2), (0, 0))}.items()}
TS = {"products": {"non_byod": {"tier": 1}, "byod": {"tier": 2}}}


def _val(cell):
    v = cell.get("userEnteredValue", {})
    return next(iter(v.values())) if v else None


class Cells(unittest.TestCase):
    def setUp(self):
        self.g = S.top_block_cells(BOX, RATES, TS)

    def test_shape(self):
        self.assertEqual(len(self.g), 9)                       # rows 4..12
        self.assertTrue(all(len(r) == 14 for r in self.g))     # A:N

    def test_box_is_one_row_per_product_with_pending_as_a_column(self):
        self.assertEqual([_val(c) for c in self.g[0][:7]],
                         ["Product", "Disconnects", "Activations", "Pending", "Churn %",
                          "0-30 Day Activation Rate", "31-60 Day Activation Rate"])
        self.assertEqual([_val(r[0]) for r in self.g[1:6]],
                         ["All Orders", "All Wireless", "BYODs", "Air", "Internet"])
        # disconnects - activations - pending
        self.assertEqual([_val(c) for c in self.g[1][1:4]], [34, 249, 207])
        self.assertEqual([_val(c) for c in self.g[2][1:4]], [16, 123, 139])
        self.assertEqual([_val(c) for c in self.g[4][1:4]], [3, 7, 2])
        self.assertEqual([_val(c) for c in self.g[5][1:4]], [0, 2, 0])
        # no row is a "... Pending" row any more
        self.assertFalse(any("Pending" in str(_val(r[0])) for r in self.g[1:]))
        # nothing under the fifth product
        for r in self.g[6:]:
            self.assertEqual(r[:7], [{}] * 7)

    def test_churn_is_disconnects_over_activations(self):
        self.assertEqual(_val(self.g[1][4]), '=IFERROR(B5/C5,"")')
        self.assertEqual(_val(self.g[5][4]), '=IFERROR(B9/C9,"")')
        self.assertEqual(self.g[1][4]["userEnteredFormat"]["numberFormat"]["pattern"], "0.00%")

    def test_rates_banded_and_blank_without_sales(self):
        f = self.g[1][5]                                       # All Orders 0-30: 53.2% = red band
        self.assertEqual(_val(f), round(250 / 470, 4))
        self.assertEqual(f["userEnteredFormat"]["backgroundColor"], S.VF.BAND_BG["red"])
        self.assertEqual(f["userEnteredFormat"]["numberFormat"]["pattern"], "0.0%")
        air = self.g[4][5]                                     # 77.8% = green band
        self.assertEqual(air["userEnteredFormat"]["backgroundColor"], S.VF.BAND_BG["green"])
        self.assertIsNone(_val(self.g[1][6]))                  # 31-60 with no sales: blank, not 0%
        self.assertEqual(self.g[1][6]["userEnteredFormat"]["backgroundColor"], S.WHITE)
        self.assertEqual(_val(self.g[3][6]), 0.9)              # BYODs 31-60: 9 of 10

    def test_gap_column_and_charts(self):
        for r in self.g:
            self.assertEqual(r[7], {})                         # H stays blank
        self.assertIn("Port Non-BYOD", _val(self.g[0][8]))     # I4
        self.assertIn("Port BYOD", _val(self.g[0][11]))        # L4
        self.assertIsNone(_val(self.g[0][9]))                  # merged-away title cells
        self.assertEqual([_val(c) for c in self.g[2][8:14]],
                         ["Tier", "0-30 Day", "OOF / INFP $"] * 2)
        self.assertEqual([_val(r[8]) for r in self.g[3:7]],
                         ["Tier 4", "Tier 3", "Tier 2", "Tier 1 ◀ now"])
        self.assertEqual([_val(r[11]) for r in self.g[3:7]],
                         ["Tier 4", "Tier 3", "Tier 2 ◀ now", "Tier 1"])
        t90n, t90b = comp.notice_90(False), comp.notice_90(True)
        oof, infp = comp.payout(f"4-{t90n}", False)
        boof, binfp = comp.payout(f"4-{t90b}", True)
        self.assertEqual(_val(self.g[3][10]), f"${oof} / ${infp}")
        self.assertEqual(_val(self.g[3][13]), f"${boof} / ${binfp}")
        self.assertEqual(_val(self.g[3][9]), comp.NONBYOD_0_30_LABEL[4])
        self.assertEqual(_val(self.g[3][12]), comp.BYOD_0_30_LABEL[4])
        for r in self.g[7:]:                                   # rows 11-12: nothing
            self.assertEqual(r, [{}] * 14)

    def test_labels_only_for_a_new_tab(self):
        g = S.top_block_cells(None, None, None)
        self.assertEqual(_val(g[1][0]), "All Orders")
        self.assertEqual([_val(c) for c in g[1][1:7]], [None] * 6)
        self.assertEqual(_val(g[6][8]), "Tier 1")              # no live marker


def _rng(r0, r1, c0, c1, sid=7):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _grad(*cells):
    return {"ranges": [_rng(r, r + 1, c, c + 1) for r, c in cells],
            "gradientRule": {"minpoint": {"type": "NUMBER", "value": "0"}}}


OLD_MERGES = [{"sheetId": 7, "startRowIndex": 0, "endRowIndex": 1, "endColumnIndex": 14},   # A1:N1
              {"sheetId": 7, "startRowIndex": 1, "endRowIndex": 2, "endColumnIndex": 14},   # A2:N2
              _rng(3, 5, 7, 10), _rng(3, 5, 10, 14),                                         # H4:J5, K4:N5
              {"sheetId": 7, "startRowIndex": 12, "endRowIndex": 14, "endColumnIndex": 14}]  # A13:N14
OLD_RULES = [{"ranges": [_rng(15, 98, 0, 14)], "booleanRule": {}},
             _grad((4, 3), (6, 3), (8, 3)), _grad((10, 3))]       # D5/D7/D9 and D11


class Requests(unittest.TestCase):
    def test_from_the_eight_row_layout(self):
        reqs = S.top_block_requests(7, S.top_block_cells(BOX, RATES, TS), OLD_MERGES, OLD_RULES)
        un = [r["unmergeCells"]["range"] for r in reqs if "unmergeCells" in r]
        self.assertEqual(un, [_rng(3, 5, 7, 10), _rng(3, 5, 10, 14)])   # only the block's merges
        up = [r["updateCells"] for r in reqs if "updateCells" in r]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0]["range"], _rng(3, 12, 0, 14))             # A4:N12
        self.assertEqual(up[0]["fields"], "userEnteredValue,userEnteredFormat")
        self.assertEqual(len(up[0]["rows"]), 9)
        mg = [r["mergeCells"]["range"] for r in reqs if "mergeCells" in r]
        self.assertEqual(mg, [_rng(3, 5, 8, 11), _rng(3, 5, 11, 14)])    # I4:K5, L4:N5
        cf = {r["updateConditionalFormatRule"]["index"]:
              r["updateConditionalFormatRule"]["rule"]["ranges"]
              for r in reqs if "updateConditionalFormatRule" in r}
        self.assertEqual(cf, {1: [_rng(4, 5, 4, 5), _rng(5, 6, 4, 5), _rng(6, 7, 4, 5)],   # E5:E7
                              2: [_rng(7, 8, 4, 5)]})                                       # E8
        # order: unmerge, then the cells, then the merges
        kinds = [next(iter(r)) for r in reqs]
        self.assertLess(kinds.index("unmergeCells"), kinds.index("updateCells"))
        self.assertLess(kinds.index("updateCells"), kinds.index("mergeCells"))

    def test_second_run_moves_no_colour_rule(self):
        merges = OLD_MERGES[:2] + [_rng(3, 5, 8, 11), _rng(3, 5, 11, 14)] + OLD_MERGES[4:]
        rules = [OLD_RULES[0], _grad((4, 4), (5, 4), (6, 4)), _grad((7, 4))]
        reqs = S.top_block_requests(7, S.top_block_cells(BOX, RATES, TS), merges, rules)
        self.assertFalse([r for r in reqs if "updateConditionalFormatRule" in r])
        self.assertEqual(len([r for r in reqs if "mergeCells" in r]), 2)

    def test_born_layout_and_strangers(self):
        # the LUCY CHURN duplicate: wireless on D5, Air on D6; a gradient
        # elsewhere on the tab is not ours
        rules = [_grad((4, 3)), _grad((5, 3)), _grad((20, 9))]
        got = S.churn_colour_requests(7, rules)
        self.assertEqual([r["updateConditionalFormatRule"]["index"] for r in got], [0, 1])


if __name__ == "__main__":
    unittest.main()
