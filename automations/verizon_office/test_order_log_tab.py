import datetime as dt
import tempfile
import unittest
from pathlib import Path

import openpyxl

from automations.verizon_office import order_log_tab as T

D = dt.datetime(2026, 11, 9)
H = T.HEADERS
C = T._COL

BASE_COLS = ["Sales Agent Name", "Signed Date", "Product Category", "Status Code",
             "Current Line Status", "Cancel Date", "Activation Date", "Order Number",
             "LineID", "Product Name", "Item Desc", "SKU Type", "Port Indicator",
             "Port Carrier", "AP_Comp_Ind"]


def _file(extra_cols=(), extra_vals=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Order Detail"
    ws.append(["Sales Verification"])                      # a banner row above the header
    ws.append(BASE_COLS + list(extra_cols))
    x = list(extra_vals)
    ws.append(["Diego  Chacon", D, "Base Plan", "APPR", "", None, None, "Q_1001", "*1-PLAN",
               "Unlimited Plus - New", "", "", "", "", ""] + x)
    ws.append(["Diego  Chacon", D, "Optional Features", "APPR", "", None, None, "Q_1001", "1-OPT",
               "Mobile Protect - New", "", "", "", "", ""] + x)
    ws.append(["Diego  Chacon", D, "Wireless Line", "APPR", "Activated", None, dt.datetime(2026, 11, 11),
               "Q_1001", "1", "Wireless Line - New", "IP17 256GB BLK", "NEW", "Y", "T-Mobile", "New"] + x)
    ws.append(["Will Bautista", dt.datetime(2026, 11, 8), "Wireless Line", "APPR", "Submitted", None, None,
               "Q_1002", "1", "Wireless Line - New", "GALAXY A17", "NEW", "N", "", ""] + x)
    ws.append(["Will Bautista", dt.datetime(2026, 10, 1), "Wireless Line", "CAN", "Disc. Post", dt.datetime(2026, 10, 20),
               dt.datetime(2026, 10, 2), "Q_0900", "1", "Wireless Line - New", "", "", "N", "", ""] + x)
    td = tempfile.mkdtemp()
    p = Path(td) / "sv.xlsx"
    wb.save(p)
    return p


class LinesTest(unittest.TestCase):
    def test_wireless_lines_in_tab_shape(self):
        ls = T.lines(_file())
        self.assertEqual(len(ls), 3)
        by = {(l["Order #"], l["Line"]): l for l in ls}
        a = by[("1001", "1")]
        self.assertEqual(a["Rep"], "Diego Chacon")
        self.assertEqual(a["Plan"], "Unlimited Plus")
        self.assertEqual(a["Add-ons"], "Mobile Protect")
        self.assertEqual(a["AutoPay"], "Yes")
        self.assertEqual((a["Type"], a["Port Carrier"], a["Device"]), ("Port", "T-Mobile", "IP17 256GB BLK"))
        self.assertEqual((a["Line Status"], a["Activation Date"]), ("Active", "11/11/2026"))
        self.assertEqual(by[("1002", "1")]["Line Status"], "Submitted")
        self.assertEqual(by[("0900", "1")]["Line Status"], "Disconnected")
        # no customer column in the file -> blank, not a crash
        self.assertEqual(a["Customer"], "")

    def test_optional_customer_columns_picked_up_by_header(self):
        ls = T.lines(_file(["CustomerName", "MTN", "Zip Code"], ["JANE DOE", "2145550100", "75050"]))
        a = ls[0]
        self.assertEqual((a["Customer"], a["Phone #"], a["Zip"]), ("Jane Doe", "2145550100", "75050"))

    def test_changed_file_is_refused(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Order Detail"
        ws.append(["Sales Agent Name", "Signed Date"])
        p = Path(tempfile.mkdtemp()) / "sv.xlsx"
        wb.save(p)
        with self.assertRaises(ValueError):
            T.lines(p)

    def test_probe_names_columns_not_values(self):
        table = T.probe(_file(["CustomerName"], ["JANE DOE"]))
        names = [r[0] for r in table[1:]]
        self.assertIn("CustomerName", names)
        self.assertNotIn("JANE", repr(table))
        row = next(r for r in table if r[0] == "CustomerName")
        self.assertEqual(row[3], "optional -> Customer")


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 11, 13)
        self.lines = T.lines(_file(["CustomerName"], ["JANE DOE"]))

    def test_first_fill_computes_week_pay_churn(self):
        r = T.merge([], self.lines, today=self.today)
        rows = {(x[C["Order #"]], x[C["Line"]]): x for x in r["rows"]}
        a = rows[("1001", "1")]
        self.assertEqual(a[C["Week Ending"]], "11/14/2026")          # Sun-Sat week of 11/9
        # activated Wed 11/11 -> week 11/8-11/14, paid Fri 11/20 + 1 week = 11/27
        self.assertEqual(a[C["Pay Period"]], "11/8-11/14 • Paid 11/27")
        self.assertEqual(a[C["Churn Bucket"]], "0-30 Day")
        self.assertEqual(rows[("1002", "1")][C["Pay Period"]], "Pending")
        self.assertEqual(rows[("0900", "1")][C["Pay Period"]], "Disconnected")
        self.assertEqual(a[C["Last Updated"]], "11/13/2026")
        self.assertEqual(r["added"], 3)

    def test_carry_notes_keep_forgotten_age_out(self):
        first = T.merge([], self.lines, today=self.today)["rows"]
        # Carlos types a note and marks one as being worked on
        for x in first:
            if (x[C["Order #"]], x[C["Line"]]) == ("1002", "1"):
                x[C["Notes"]] = "called 11/13"
                x[C["Being worked on"]] = "Yes"
        # three weeks on: 1002 activated, 1001 forgotten by Credico, the 10/1
        # order is now 65 days old
        later = dt.date(2026, 12, 5)
        nxt = [dict(l) for l in self.lines if l["Order #"] == "1002"]
        nxt[0]["Line Status"], nxt[0]["Activation Date"] = "Active", "11/13/2026"
        r = T.merge(first, nxt, today=later, existing_header=list(H))
        rows = {(x[C["Order #"]], x[C["Line"]]): x for x in r["rows"]}
        self.assertIn(("1001", "1"), rows)                         # kept though the feed forgot it
        self.assertEqual(rows[("1001", "1")][C["Last Updated"]], "11/13/2026")
        b = rows[("1002", "1")]
        self.assertEqual((b[C["Notes"]], b[C["Being worked on"]]), ("called 11/13", "Yes"))
        self.assertEqual(b[C["Last Updated"]], "12/05/2026")       # state changed -> restamped
        self.assertEqual(b[C["Pay Period"]], "11/8-11/14 • Paid 11/27")
        self.assertEqual(r["changed"], 1)
        self.assertNotIn(("0900", "1"), rows)                      # past DAYS_KEPT by Order Date
        self.assertEqual(r["aged_out"], 1)

    def test_fresh_blank_never_erases_typed_customer_data(self):
        first = T.merge([], self.lines, today=self.today)["rows"]
        for x in first:
            x[C["Phone #"]] = "2145550100"
        r = T.merge(first, self.lines, today=self.today, existing_header=list(H))
        self.assertTrue(all(x[C["Phone #"]] == "2145550100" for x in r["rows"]))

    def test_old_layout_remaps_by_header(self):
        old_header = ["Rep", "Order #", "Line", "Notes"]
        old_rows = [["Diego Chacon", "1001", "1", "keep me"]]
        r = T.merge(old_rows, self.lines, today=self.today, existing_header=old_header)
        a = next(x for x in r["rows"] if x[C["Order #"]] == "1001")
        self.assertEqual(a[C["Notes"]], "keep me")


class GuardTest(unittest.TestCase):
    def test_tab_is_not_protected_and_sandbox_is_default(self):
        self.assertNotIn(T.TAB, T.PROTECTED_TABS)
        self.assertNotEqual(T.SANDBOX_SHEET_ID, T.PROD_SHEET_ID)
        import inspect
        self.assertEqual(inspect.signature(T.push).parameters["sheet_id"].default, T.SANDBOX_SHEET_ID)


if __name__ == "__main__":
    unittest.main()
