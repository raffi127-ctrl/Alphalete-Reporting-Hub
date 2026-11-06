"""Sahil 2026-11-05: his reps' tabs show Pending / Cancels only — no "Paid
Friday" week sections, no pay columns. Every other office is unchanged.

  python -m unittest automations.uploaded.test_order_log_no_pay_tabs
"""
import unittest
from datetime import date

from openpyxl import Workbook

from automations.uploaded import order_log as ol
from automations.uploaded.test_order_log_pay_period import _log

TODAY = date(2026, 11, 5)
ROWS = [
    ("Alyssa Parks", date(2026, 11, 2), "Active"),
    ("Alyssa Parks", date(2026, 11, 3), "Scheduled"),
    ("Alyssa Parks", date(2026, 11, 2), "Cancelled"),
    ("Only Paid Pat", date(2026, 11, 3), "Active"),
]


def _texts(owner):
    wb = Workbook()
    wb.active.title = "Cleaned Order Log"
    ol._append_rep_breakdown_tabs(wb, _log(ROWS), owner=owner, today=TODAY)
    return {n: [c for row in wb[n].iter_rows(values_only=True) for c in row
                if isinstance(c, str)] for n in wb.sheetnames[1:]}


class SahilTabsHaveNoPaycheck(unittest.TestCase):
    def test_sahil_tab_is_pending_and_cancels_only(self):
        tabs = _texts("Sahil Multani")
        alyssa = tabs["Alyssa Parks"]
        self.assertIn("Pending / Disconnect / Cancel", alyssa)
        self.assertIn("Activation/Pay Week", alyssa)     # calendar stays
        self.assertFalse([t for t in alyssa if "Paid Friday" in t])
        self.assertNotIn("Active", alyssa)               # paid line gone

    def test_sahil_rep_with_only_paid_sales_gets_no_tab(self):
        self.assertNotIn("Only Paid Pat", _texts("Sahil Multani"))

    def test_other_offices_keep_the_paid_weeks(self):
        tabs = _texts("Starr Rodenhurst")
        self.assertTrue([t for t in tabs["Alyssa Parks"] if "Paid Friday" in t])
        self.assertIn("Only Paid Pat", tabs)


if __name__ == "__main__":
    unittest.main()
