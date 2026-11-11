"""Carlos 2026-11-09: "on this NDS order log report we need to add in the
phone number for each line. in between the package and status column" --
the crew's per-rep tabs carry the line's number (spe.TN) between Package
and Status, headed Phone Number. 2026-11-10 ("can we also add in the zip
code on file"): Zip Code (the export's Customer Zip Simple) right after it,
and Customer Zip at the end of the crew's All tab. 2026-11-11 ("Let's add
in: the wireless order number, BAN, the line, the type, device, ship date,
delivered, port status, last updated"): the Vantura NDS Order Log tab's own
columns ride the crew's workbook too, each Tableau line joined to its tab
row by the line's phone number (order_log_tab.LineIndex). The house NDS rep
tabs and All tab (Raf's offices) are unchanged.

  python -m unittest automations.nds_metrics.test_order_log_rep_tabs
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from automations.nds_metrics import order_log_tab as T
from automations.nds_metrics import run as R
from automations.office_metrics import nds_orderlog as NOL
from automations.uploaded import order_log as ol

HEADER = ["Owner Name", "Rep", "sp.Order Date", "DTR Active Date", "spe.TN",
          "Customer Name", "Customer Zip Simple", "sp.SPM Number", "Package",
          "spe.Status", "spe.Install Date", "Bonus Eligible $",
          "spe.Wireless Type", "Product Type (Broken Out)",
          "Wireless Installment Plan", "spe.TN Type", "spe.Port Carrier",
          "spe.Name", "Measure Names"]
CREW_TAB_HEADER = ["Order Date", "Activation Date", "Customer Name",
                   "SPM Number", "Wireless Order #", "BAN", "Line", "Line Type",
                   "Type", "Device", "Next Up", "Package", "Phone Number",
                   "Zip Code", "Status", "Churn Bucket", "Ship Date", "Delivered",
                   "Port Status", "Last Updated", "Install Date", "Ported From",
                   "Tier Bonus $"]
TAB_FRIENDLY = [wb for _tab, wb in R.CREW_TAB_COLUMNS]
TODAY = dt.date(2026, 11, 9)


def _row(**kw):
    base = {"Owner Name": "Carlos Hidalgo", "Rep": "Ana Lopez",
            "sp.Order Date": "11/3/2026", "DTR Active Date": "",
            "spe.TN": "", "Customer Name": "CARLOS JAVIER P",
            "Customer Zip Simple": "75060",
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
            "Customer Name": "DEISY P", "Customer Zip Simple": "76017",
            "sp.SPM Number": "DSI284253567",
            "spe.Status": "Port Approved", "spe.Name": "SPE-2"}),
]


def _tab_line(**kw):
    base = {"rep": "Ana Lopez", "customer": "CARLOS JAVIER P", "order_date": "11/3/2026",
            "dsi": "DSI283400221", "wireless_order": "99-617486262558479",
            "ban": "177145738935", "line_no": "2", "line_type": "Port",
            "device": "214-555-0100", "line_number": "Smartphone",
            "line_phone": "iPhone 18 Pro - 256GB - Black", "plan": "AT&T Premium 2.0",
            "line_status": "Active", "ship_date": "11/4/2026", "delivered": "11/6/2026",
            "port_status": "8A"}
    base.update(kw)
    return base


def _tab_rows():
    """Two tab rows (order_log_tab.HEADERS order): ROWS[0]'s line by its
    number, and a line of an order the export doesn't carry."""
    return [T.line_row(_tab_line(), "11/08/2026"),
            T.line_row(_tab_line(customer="OTHER C", dsi="DSI999", wireless_order="",
                                 ban="", line_no="1", device="214-555-0999"), "11/09/2026")]


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


def _crew_kw(index=None):
    return dict(rep_tab_columns=R.CREW_REP_TAB_COLUMNS,
                rep_tab_display=R.CREW_REP_TAB_DISPLAY,
                extra_columns=R.crew_extra_columns(index),
                text_columns=R.CREW_TEXT_COLUMNS)


def _by_customer(data):
    i = CREW_TAB_HEADER.index("Customer Name")
    return {r[i]: r for r in data}


class CrewRepTabsCarryThePhoneNumber(unittest.TestCase):
    def test_phone_number_sits_between_package_and_status(self):
        all_hdr, headers, data = _build(**_crew_kw())
        self.assertEqual(len(headers), 2)           # week section + P/D/C
        for h in headers:
            self.assertEqual(h, CREW_TAB_HEADER)
        phones = sorted(_digits(r[CREW_TAB_HEADER.index("Phone Number")])
                        for r in data)
        self.assertEqual(phones, ["2145550100", "2145550101"])
        # The All tab is as it was, plus the extras at the very end: the
        # number stays at D as Customer Phone.
        self.assertEqual(all_hdr, NOL._NDS_FRIENDLY_HEADERS
                         + ["Customer Zip", "Churn Bucket"] + TAB_FRIENDLY)

    def test_zip_code_sits_after_the_phone_number(self):
        _all, headers, data = _build(**_crew_kw())
        for h in headers:
            self.assertEqual(h.index("Zip Code"), h.index("Phone Number") + 1)
            self.assertEqual(h.index("Zip Code"), h.index("Status") - 1)
        zips = sorted(_digits(r[CREW_TAB_HEADER.index("Zip Code")]) for r in data)
        self.assertEqual(zips, ["75060", "76017"])

    def test_churn_bucket_sits_after_status(self):
        # Row 1 posted 11/5 (age 4 on 11/9) -> the live window; row 2 has not
        # posted -> blank. The All tab carries it after the zip.
        all_hdr, headers, data = _build(**_crew_kw())
        for h in headers:
            self.assertEqual(h.index("Churn Bucket"), h.index("Status") + 1)
        got = {r[CREW_TAB_HEADER.index("Customer Name")]: r[CREW_TAB_HEADER.index("Churn Bucket")]
               for r in data}
        self.assertEqual(got["CARLOS JAVIER P"], "0-30 Day")
        self.assertIn(got["DEISY P"], (None, ""))
        n = len(NOL._NDS_FRIENDLY_HEADERS)
        self.assertEqual(all_hdr[n:n + 2], ["Customer Zip", "Churn Bucket"])

    def test_churn_bucket_edges_follow_tableaus_columns(self):
        today = dt.date(2026, 11, 11)
        for age, want in [(0, "0-30 Day"), (30, "0-30 Day"), (31, "30 Day"), (60, "30 Day"),
                          (61, "60 Day"), (90, "60 Day"), (91, "90 Day"), (120, "90 Day"),
                          (121, "120 Day"), (150, "120 Day"), (151, "150+ Day")]:
            self.assertEqual(NOL.churn_bucket(today - dt.timedelta(days=age), today), want, age)
        self.assertEqual(NOL.churn_bucket(None, today), "")
        self.assertEqual(NOL.churn_bucket(today + dt.timedelta(days=1), today), "")

    def test_house_nds_rep_tabs_are_unchanged(self):
        all_hdr, headers, _data = _build()
        house = [h for h in NOL._NDS_FRIENDLY_HEADERS
                 if h not in ("Rep", "Customer Phone")]
        for h in headers:
            self.assertEqual(h, house)
            for extra in ("Phone Number", "Zip Code", "Churn Bucket", "BAN",
                          "Line Type", "Last Updated"):
                self.assertNotIn(extra, h)
        self.assertEqual(all_hdr, NOL._NDS_FRIENDLY_HEADERS)   # no extras for Raf's offices

    def test_house_fiber_profile_restored_after_a_crew_build(self):
        _build(**_crew_kw(T.LineIndex(_tab_rows())))
        self.assertIn("Customer Phone", ol._REP_TAB_COLUMNS)   # fiber keeps it
        self.assertEqual(ol._REP_TAB_DISPLAY, {"Customer Phone": "Customer Number"})
        self.assertEqual(ol.FRIENDLY_HEADERS[0], "Rep")
        self.assertNotIn("Customer Zip", ol.FRIENDLY_HEADERS)
        self.assertEqual(ol.TEXT_RAW_COLUMNS, ())
        self.assertEqual(NOL._NDS_FRIENDLY_HEADERS[-1], "Tier Bonus $")   # house list untouched

    def test_crew_layout_pinned(self):
        cols = R.CREW_REP_TAB_COLUMNS
        self.assertEqual(cols.index("Customer Phone"), cols.index("Package") + 1)
        self.assertEqual(cols.index("Customer Zip"), cols.index("Customer Phone") + 1)
        self.assertEqual(cols.index("Customer Zip"), cols.index("Status") - 1)
        self.assertEqual(cols.index("Churn Bucket"), cols.index("Status") + 1)
        self.assertEqual(set(cols),
                         (set(NOL._NDS_FRIENDLY_HEADERS) - {"Rep"})
                         | {"Customer Zip", "Churn Bucket"} | set(TAB_FRIENDLY))
        self.assertEqual(len(cols), len(set(cols)))
        self.assertEqual(R.CREW_REP_TAB_DISPLAY,
                         {"Customer Phone": "Phone Number", "Customer Zip": "Zip Code"})
        self.assertEqual([x[1] for x in R.CREW_EXTRA_COLUMNS], ["Customer Zip", "Churn Bucket"])
        self.assertEqual([x[1] for x in R.crew_extra_columns(None)],
                         ["Customer Zip", "Churn Bucket"] + TAB_FRIENDLY)
        self.assertEqual(R.CREW_TEXT_COLUMNS, ("Wireless Order #", "BAN"))

    def test_unknown_rep_tab_column_refuses(self):
        with self.assertRaises(ValueError):
            with ol.column_profile(NOL._NDS_COLUMNS_TO_KEEP, NOL._NDS_FRIENDLY_HEADERS,
                                   rep_tab_columns=["Order Date", "Nope"]):
                pass


class CrewRepTabsCarryTheTabColumns(unittest.TestCase):
    """Carlos 2026-11-11: the Vantura NDS Order Log tab's columns on the
    crew's workbook, by the line's phone number."""

    def test_tab_columns_fill_by_the_lines_number(self):
        _all, headers, data = _build(**_crew_kw(T.LineIndex(_tab_rows())))
        for h in headers:
            self.assertEqual(h, CREW_TAB_HEADER)
        rows = _by_customer(data)
        got = {h: rows["CARLOS JAVIER P"][CREW_TAB_HEADER.index(h)] for h in TAB_FRIENDLY}
        self.assertEqual(got, {"Wireless Order #": "99-617486262558479",
                               "BAN": "177145738935", "Line": 2, "Line Type": "Port",
                               "Device": "iPhone 18 Pro - 256GB - Black",
                               "Ship Date": "11/4/2026", "Delivered": "11/6/2026",
                               "Port Status": "8A", "Last Updated": "11/08/2026"})
        self.assertIsInstance(got["BAN"], str)             # text, never 1.77E+11
        # the second line's number is not on the tab and its order has no tab
        # line either: every tab column blank, nothing guessed
        for h in TAB_FRIENDLY:
            self.assertIn(rows["DEISY P"][CREW_TAB_HEADER.index(h)], (None, ""), h)
        # the workbook's own columns are untouched by the join
        self.assertEqual(rows["CARLOS JAVIER P"][CREW_TAB_HEADER.index("Type")], "Phone")
        self.assertEqual(_digits(rows["CARLOS JAVIER P"][CREW_TAB_HEADER.index("Phone Number")]),
                         "2145550100")

    def test_tab_columns_are_blank_without_tab_rows(self):
        all_hdr, headers, data = _build(**_crew_kw(None))
        self.assertEqual(all_hdr[-len(TAB_FRIENDLY):], TAB_FRIENDLY)
        for r in data:
            for h in TAB_FRIENDLY:
                self.assertIn(r[CREW_TAB_HEADER.index(h)], (None, ""), h)

    def test_tab_column_positions(self):
        h = CREW_TAB_HEADER
        self.assertEqual(h.index("Wireless Order #"), h.index("SPM Number") + 1)
        self.assertEqual(h[h.index("SPM Number"):h.index("Type") + 1],
                         ["SPM Number", "Wireless Order #", "BAN", "Line", "Line Type", "Type"])
        self.assertEqual(h.index("Device"), h.index("Type") + 1)
        self.assertEqual(h[h.index("Churn Bucket"):h.index("Install Date") + 1],
                         ["Churn Bucket", "Ship Date", "Delivered", "Port Status",
                          "Last Updated", "Install Date"])

    def test_all_tab_carries_the_tab_columns_at_the_end(self):
        all_hdr, _h, _d = _build(**_crew_kw(T.LineIndex(_tab_rows())))
        self.assertEqual(all_hdr[-len(TAB_FRIENDLY):], TAB_FRIENDLY)


if __name__ == "__main__":
    unittest.main()
