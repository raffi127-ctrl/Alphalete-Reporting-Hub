"""Colten 2026-11-11: his NDS Order Log rep tabs carry the customer's number
(spe.TN) between Package and Status, headed Phone Number. Other Raf NDS
owners keep the house rep tabs (no number).

  python -m unittest automations.office_metrics.test_order_log_owner_phone
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from automations.office_metrics import nds_orderlog as NOL
from automations.nds_metrics.test_order_log_rep_tabs import HEADER, ROWS

TODAY = dt.date(2026, 11, 9)


def _rep_headers(owner):
    cols, disp = NOL._OWNER_REP_TABS.get(owner, (None, None))
    with tempfile.TemporaryDirectory() as tmp:
        path, _n = NOL._render_order_log(owner, HEADER, ROWS, TODAY, Path(tmp),
                                         rep_tab_columns=cols,
                                         rep_tab_display=disp)
        wb = load_workbook(path)
    out = []
    for row in wb["Ana Lopez"].iter_rows(values_only=True):
        cells = [c for c in row if c is not None]
        if cells and cells[0] == "Order Date":
            out.append(cells)
    return out


class OwnerPhone(unittest.TestCase):
    def test_colten_has_phone_between_package_and_status(self):
        hdrs = _rep_headers("Colten Wright")
        self.assertTrue(hdrs)
        for h in hdrs:
            i = h.index("Phone Number")
            self.assertEqual(h[i - 1], "Package")
            self.assertEqual(h[i + 1], "Status")

    def test_other_owner_unchanged(self):
        for h in _rep_headers("Someone Else"):
            self.assertNotIn("Phone Number", h)
            self.assertNotIn("Customer Number", h)


if __name__ == "__main__":
    unittest.main()
