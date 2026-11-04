import unittest

from automations.sales_board_fixer import extra_rows as X
from automations.sales_board_fixer.test_checks import GOOD, board


class Plan(unittest.TestCase):
    def test_spare_rows_counted_by_blank_or_placeholder_name(self):
        rows = [("Rep %d" % i, GOOD, "1", "Here") for i in range(5)]
        rows += [("ZZ EXTRA", GOOD, "", "")] * 3 + [("", GOOD, "", "")] * 2 + [("xx", GOOD, "", "")]
        v, _ = board(rows)
        p = X.plan(v)
        self.assertEqual((p.spare, p.add), (6, 4))
        self.assertEqual(p.model, 14)                   # last spare row
        self.assertFalse(p.model_is_rep)

    def test_ten_spare_rows_add_nothing(self):
        v, _ = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(5)]
                     + [("", GOOD, "", "")] * 10)
        self.assertEqual(X.plan(v).add, 0)

    def test_no_spare_rows_inserts_inside_the_block_with_formulas_only(self):
        v, _ = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(6)])
        p = X.plan(v)
        self.assertEqual((p.spare, p.add, p.model, p.at), (0, 10, 9, 9))
        self.assertTrue(p.model_is_rep)
        model = [{"userEnteredValue": {"stringValue": "Rep 5"}},
                 {"userEnteredValue": {"formulaValue": "=SUM(E9)"}, "userEnteredFormat": {"x": 1}},
                 {"userEnteredValue": {"numberValue": 3}}]
        reqs = X.requests(7, p, False, model)
        ins = reqs[0]["insertDimension"]["range"]
        # rows land ABOVE the last rep (index 8 = row 9) so SUM(D4:D9) grows
        self.assertEqual((ins["startIndex"], ins["endIndex"]), (8, 18))
        # the rep goes back up to row 9; the blanks are rows 10-19
        mv = reqs[1]["moveDimension"]
        self.assertEqual((mv["source"]["startIndex"], mv["destinationIndex"]), (18, 8))
        self.assertEqual(reqs[2]["updateCells"]["range"]["startRowIndex"], 9)
        rows = reqs[2]["updateCells"]["rows"]
        self.assertEqual(rows[0]["values"][1]["userEnteredValue"]["formulaValue"], "=SUM(E10)")
        self.assertEqual(rows[9]["values"][1]["userEnteredValue"]["formulaValue"], "=SUM(E19)")
        self.assertEqual(rows[0]["values"][1]["userEnteredFormat"], {"x": 1})
        self.assertNotIn("userEnteredValue", rows[0]["values"][0])   # never the rep's name
        self.assertNotIn("userEnteredValue", rows[0]["values"][2])   # nor their numbers
        self.assertEqual(len(reqs), 3)

    def test_hidden_spare_model_keeps_its_placeholder_and_is_hidden(self):
        v, _ = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(5)]
                     + [("ZZ EXTRA", GOOD, "", "")] * 7)
        p = X.plan(v)
        reqs = X.requests(7, p, True, [{"userEnteredValue": {"stringValue": "ZZ EXTRA"}}])
        self.assertEqual(reqs[1]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"],
                         {"stringValue": "ZZ EXTRA"})
        self.assertIn("updateDimensionProperties", reqs[2])


class Totals(unittest.TestCase):
    def test_totals_that_stop_short_are_stretched_to_the_last_row(self):
        f = [[""]] * 20 + [["", "Total", "=SUM(C4:C20)", '=SUMIF($BN$4:$BN$20,"<>RT",D4:D20)',
                            "=SUM(E4:E31)", "=C2/C3"]]
        out = X.short_totals(f, 4, 20)
        self.assertEqual(out, {})                           # already reaches row 20
        out = X.short_totals([[""]] * 30 + [f[-1]], 4, 30)
        self.assertEqual(out["C31"], "=SUM(C4:C30)")
        self.assertEqual(out["D31"], '=SUMIF($BN$4:$BN$30,"<>RT",D4:D30)')
        self.assertNotIn("E31", out)                        # past the block: left alone
        self.assertNotIn("F31", out)


if __name__ == "__main__":
    unittest.main()
