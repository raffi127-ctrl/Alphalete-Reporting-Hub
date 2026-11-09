"""Carlos 2026-11-09: "on this NDS order log report we need to add in the
phone number for each line. in between the package and status column" --
the crew's per-rep tabs carry the line's number (spe.TN) between Package
and Status, headed Phone Number. The All tab and the house NDS rep tabs
(Raf's offices) are unchanged.

  python -m unittest automations.nds_metrics.test_order_log_rep_tabs
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from automations.nds_metrics import run as R
from automations.office_metrics import nds_orderlog as NOL
from automations.uploaded import order_log as ol

HEADER = ["Owner Name", "Rep", "sp.Order Date", "DTR Active Date", "spe.TN",
          "Customer Name", "sp.SPM Number", "Package", "spe.Status",
          "spe.Install Date", "Bonus Eligible $", "spe.Wireless Type",
          "Product Type (Broken Out)", "Wireless Installment Plan",
          "spe.TN Type", "spe.Port Carrier", "spe.Name", "Measure Names"]
CREW_TAB_HEADER = ["Order Date", "Activation Date", "Customer Name",
                   "SPM Number", "Type", "Next Up", "Package", "Phone Number",
                   "Status", "Install Date", "Ported From", "Tier Bonus $"]
TODAY = dt.date(2026, 11, 9)


def _row(**kw):
    base = {"Owner Name": "Carlos Hidalgo", "Rep": "Ana Lopez",
            "sp.Order Date": "11/3/2026", "DTR Active Date": "",
            "spe.TN": "", "Customer Name": "CARLOS JAVIER P",
            "sp.SPM Number": "DSI283400221", "Package": "AT&T Premium 2.0",
            "spe.Status": "Active", "spe.Install Date": "",
            "Bonus Eligible $": "", "spe.Wireless Type": "Phone",
            "Product Type (Broken Out)": "Wireless",
            "Wireless Installment Plan": "Next Up", "spe.TN Type": "port",
            "spe.Port Carrier": "T-MOBILE USA", "spe.Name": "SPE-1",
            "Measure Names": "Unit Count"}
    base.update(kw)
    return [base[h] for h in HEADER]


ROWS = [
    _row(**{"DTR Active Date": "11/5/2026", "spe.TN": "2145550100"}),
    _row(**{"sp.Order Date": "11/7/2026", "spe.TN": "2145550101",
            "Customer Name": "DEISY P", "sp.SPM Number": "DSI284253567",
            "spe.Status": "Port Approved", "spe.Name": "SPE-2"}),
]


def _digits(v) -> str:
    return str(int(v)) if isinstance(v, (int, float)) else str(v or "")


def _build(**kw):
    """-> (All-tab header, [rep-tab header rows], [rep-tab data rows])."""
    with tempfile.TemporaryDirectory() as tmp:
        path, n = NOL._render_order_log("Carlos Hidalgo", HEADER, ROWS, TODAY,
                                        Path(tmp), **kw)
        wb = load_workbook(path)
    all_hdr = [c.value for c in wb["Cleaned Order Log"][1]]
    rep = wb["Ana Lopez"]
    headers, data = [], []
    for row in rep.iter_rows(values_only=True):
        cells = [c for c in row if c is not None]
        if cells and cells[0] == "Order Date":
            headers.append(list(cells))
        elif cells and cells[0] not in (None, "Week Start") and hasattr(cells[0], "year") and len(cells) > 3:
            data.append(list(row))
    return all_hdr, headers, data


class CrewRepTabsCarryThePhoneNumber(unittest.TestCase):
    def test_phone_number_sits_between_package_and_status(self):
        all_hdr, headers, data = _build(rep_tab_columns=R.CREW_REP_TAB_COLUMNS,
                                        rep_tab_display=R.CREW_REP_TAB_DISPLAY)
        self.assertEqual(len(headers), 2)           # week section + P/D/C
        for h in headers:
            self.assertEqual(h, CREW_TAB_HEADER)
        phones = sorted(_digits(r[CREW_TAB_HEADER.index("Phone Number")])
                        for r in data)
        self.assertEqual(phones, ["2145550100", "2145550101"])
        # The All tab is as it was: the number stays at D as Customer Phone.
        self.assertEqual(all_hdr, NOL._NDS_FRIENDLY_HEADERS)

    def test_house_nds_rep_tabs_are_unchanged(self):
        _all, headers, _data = _build()
        house = [h for h in NOL._NDS_FRIENDLY_HEADERS
                 if h not in ("Rep", "Customer Phone")]
        for h in headers:
            self.assertEqual(h, house)
            self.assertNotIn("Phone Number", h)

    def test_house_fiber_profile_restored_after_a_crew_build(self):
        _build(rep_tab_columns=R.CREW_REP_TAB_COLUMNS,
               rep_tab_display=R.CREW_REP_TAB_DISPLAY)
        self.assertIn("Customer Phone", ol._REP_TAB_COLUMNS)   # fiber keeps it
        self.assertEqual(ol._REP_TAB_DISPLAY, {"Customer Phone": "Customer Number"})
        self.assertEqual(ol.FRIENDLY_HEADERS[0], "Rep")

    def test_crew_layout_pinned(self):
        cols = R.CREW_REP_TAB_COLUMNS
        self.assertEqual(cols.index("Customer Phone"), cols.index("Package") + 1)
        self.assertEqual(cols.index("Customer Phone"), cols.index("Status") - 1)
        self.assertEqual(set(cols), set(NOL._NDS_FRIENDLY_HEADERS) - {"Rep"})
        self.assertEqual(R.CREW_REP_TAB_DISPLAY, {"Customer Phone": "Phone Number"})

    def test_unknown_rep_tab_column_refuses(self):
        with self.assertRaises(ValueError):
            with ol.column_profile(NOL._NDS_COLUMNS_TO_KEEP, NOL._NDS_FRIENDLY_HEADERS,
                                   rep_tab_columns=["Order Date", "Nope"]):
                pass


if __name__ == "__main__":
    unittest.main()
