"""Christian Esposito, 2026-09-14: AppStream lists him under office 23783
('Resound, Inc. 2nd'), which has been empty since mid-August — his real office
is 23038, access pending. Two things must hold:

  1. a promotion PINNED to 23038 never lands on 23783, even though the name
     matches it perfectly;
  2. its backfill overwrites only the blank/0 cells 23783 left, never a week
     that already has real numbers.

    python -m unittest automations.recruiting_report.test_promote_pinned
"""
import datetime as dt
import unittest
from unittest import mock

from automations.recruiting_report import fill

WRONG = {"office_id": "23783", "owner": "Christian Esposito",
         "company": "Resound, Inc. 2nd"}
RIGHT = {"office_id": "23038", "owner": "Christian Esposito",
         "company": "Resound, Inc."}


def _mapping():
    return {"confirmed": [], "sales_only": [{
        "sheet_tab": "Christian Esposito", "as_owner": "Christian Esposito",
        "promote_when_visible": True, "promote_office_id": "23038",
        "replace_zeros_only": True}]}


class PinnedPromotion(unittest.TestCase):
    def _run(self, offices):
        index = {}
        for o in offices:
            index.setdefault(fill._norm_name(o["owner"]), []).append(o)
        with mock.patch.object(fill, "_load_office_index", return_value=index), \
                mock.patch("automations.focus_office_att.aliases.load_aliases",
                           return_value={}):
            m = _mapping()
            return m, fill.promote_visible_sales_only(m, dry_run=True)

    def test_the_wrong_office_alone_promotes_nothing(self):
        m, got = self._run([WRONG])
        self.assertEqual(got, [])
        self.assertEqual(len(m["sales_only"]), 1)

    def test_the_pinned_office_promotes_even_beside_the_wrong_one(self):
        m, got = self._run([WRONG, RIGHT])
        self.assertEqual([p["office_id"] for p in got], ["23038"])
        self.assertTrue(got[0]["replace_zeros_only"])
        self.assertEqual(m["sales_only"], [])


class ReplaceZerosOnly(unittest.TestCase):
    def test_only_blank_or_zero_cells_survive(self):
        jul, aug = dt.date(2026, 7, 26), dt.date(2026, 8, 30)
        values = [["", "WE", "7/26/26", "8/30/26"],
                  ["", "Sent To Call List", "333", "0"],
                  ["", "1ST BOOKED", "145", ""],
                  ["", "1st Retention", "48%", "0%"]]
        rows = {"pull": 2, "first_booked": 3, "first_retention": 4}
        cols = {jul: 3, aug: 4}
        data = {jul: {"pull": 999, "first_booked": 999, "first_retention": 0.9},
                aug: {"pull": 120, "first_booked": 40, "first_retention": 0.5}}
        got = fill.keep_blank_or_zero_cells(values, rows, cols, data)
        self.assertNotIn(jul, got)                    # July's real data stays
        self.assertEqual(got[aug], data[aug])         # every 0 / blank replaced

    def test_text_is_never_treated_as_zero(self):
        self.assertFalse(fill._is_blank_or_zero("7 NI"))
        self.assertTrue(fill._is_blank_or_zero("0.00%"))
        self.assertTrue(fill._is_blank_or_zero(""))


if __name__ == "__main__":
    unittest.main()
