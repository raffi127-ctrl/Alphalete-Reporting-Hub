"""Regression: a freshly-inserted WE history row must LOOK like the rows below.

The defect (Eve 2026-09-01, the morning after the roll): every Tuesday the new
'WE m.d' row landed with partial borders (C..I carried LR where every settled
row below had TBLR) and, on some stacks, without the A:B merge the other rows
use. rollover_format could repair all of it and had been able to since
2026-07-21 — nothing ever called it. The repair now runs at the INSERT, in the
one helper all three boards share.

Pure request-shape asserts: no Sheet, no network.

    python automations/org_sales_board/test_we_row_format.py
"""
from __future__ import annotations

import unittest

from automations.org_sales_board.rollover import we_row_format_requests


SHEET = 4242


class WeRowFormatRequests(unittest.TestCase):

    def setUp(self):
        self.reqs = we_row_format_requests(SHEET, top_row=574, last_col=10)
        self.merge = self.reqs[0]["mergeCells"]
        self.paste = self.reqs[1]["copyPaste"]

    def test_merge_comes_first(self):
        """Merge before paste: PASTE_FORMAT onto a row whose merge doesn't exist
        yet is what left the label sitting in A alone."""
        self.assertIn("mergeCells", self.reqs[0])
        self.assertIn("copyPaste", self.reqs[1])
        self.assertEqual(len(self.reqs), 2)

    def test_merge_is_a_b_on_the_new_row_only(self):
        r = self.merge["range"]
        self.assertEqual(r["sheetId"], SHEET)
        self.assertEqual((r["startRowIndex"], r["endRowIndex"]), (573, 574))
        self.assertEqual((r["startColumnIndex"], r["endColumnIndex"]), (0, 2))
        self.assertEqual(self.merge["mergeType"], "MERGE_ALL")

    def test_format_source_is_the_settled_row_below(self):
        """Never the Totals row ABOVE — it has no borders at all, so copying it
        would blank the very borders this repair exists to restore."""
        src = self.paste["source"]
        self.assertEqual((src["startRowIndex"], src["endRowIndex"]), (574, 575))
        dst = self.paste["destination"]
        self.assertEqual((dst["startRowIndex"], dst["endRowIndex"]), (573, 574))

    def test_paste_is_format_only(self):
        """A value paste would overwrite the week we just froze."""
        self.assertEqual(self.paste["pasteType"], "PASTE_FORMAT")
        self.assertEqual(self.paste["pasteOrientation"], "NORMAL")

    def test_last_col_is_inclusive_and_spans_from_a(self):
        for last_col in (10, 12):
            reqs = we_row_format_requests(SHEET, top_row=90, last_col=last_col)
            for side in ("source", "destination"):
                rng = reqs[1]["copyPaste"][side]
                self.assertEqual(rng["startColumnIndex"], 0)
                self.assertEqual(rng["endColumnIndex"], last_col)

    def test_country_stack_is_two_columns_wider_than_the_org_stacks(self):
        """Country's WE rows carry LAST WEEK'S / PREVIOUS WEEK'S TOTALS past the
        running total (A..L); the ORG / All Campaigns stacks stop at their
        Grand-Total (A..J). A shared constant here would clip Country's K/L."""
        org = we_row_format_requests(SHEET, top_row=574, last_col=10)
        country = we_row_format_requests(SHEET, top_row=182, last_col=12)
        self.assertEqual(org[1]["copyPaste"]["source"]["endColumnIndex"], 10)
        self.assertEqual(country[1]["copyPaste"]["source"]["endColumnIndex"], 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
