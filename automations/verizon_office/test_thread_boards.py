"""thread_boards — Credico Order Detail -> the NDS wireless boards' columns."""
import datetime as dt
import unittest

from automations.verizon_office import thread_boards as T

D = dt.date(2026, 11, 4)


class Status(unittest.TestCase):
    def test_every_status_seen_in_nicos_11_6_file(self):
        self.assertEqual(T.dtr_status("APPR", "Approved", D), "Posted")
        self.assertEqual(T.dtr_status("PEND", "Activated", D), "Posted")
        self.assertEqual(T.dtr_status("SUB", "Submitted", None), "Submitted")
        self.assertEqual(T.dtr_status("CAN", "Disc. (Pre)", D), "Disconnected")
        self.assertEqual(T.dtr_status("CAN", "Disc. (Post)", D), "Disconnected")
        self.assertEqual(T.dtr_status("CAN", "Canceled", None), "Canceled")
        self.assertEqual(T.dtr_status("REJ", "", None), "Canceled")   # Incomplete = never a sale

    def test_submitted_is_pending_on_the_house_board(self):
        from automations.office_metrics import nds_orderlog as N
        self.assertNotIn(N._house_status(T.dtr_status("SUB", "Submitted", None)),
                         ("active", "canceled", "disconnected"))


class Plan(unittest.TestCase):
    def test_plan_names_fit_the_board(self):
        self.assertEqual(T._plan("Verizon Simplicity Plan (Smartphone) - New"), "Simplicity Plan")
        self.assertEqual(T._plan("Unlimited Welcome - Byod"), "Unlimited Welcome")


class NoCustomerData(unittest.TestCase):
    def test_customer_columns_go_out_blank(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Order Detail"
        cols = ["Sales Agent Name", "Signed Date", "Product Category", "Status Code",
                "Current Line Status", "Cancel Date", "Activation Date", "Order Number",
                "LineID", "Product Name", "CustomerName", "Item Desc", "Port Indicator"]
        ws.append(cols)
        ws.append(["Diego  Chacon", D, "Base Plan", "APPR", "", None, None, "Q_1", "*1-PLAN",
                   "Unlimited Plus - New", "JANE DOE", "", ""])
        ws.append(["Diego  Chacon", D, "Wireless Line", "APPR", "Approved", None, D, "Q_1",
                   "*1-LINE", "Wireless Line - New", "JANE DOE", "IP17 256GB BLK", "N"])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sv.xlsx"
            wb.save(p)
            header, rows = T.nds_rows(p)
        self.assertEqual(len(rows), 1)
        r = dict(zip(header, rows[0]))
        self.assertEqual((r["Rep"], r["DTR Status"], r["Package"], r["sp.SPM Number"]),
                         ("Diego Chacon", "Posted", "Unlimited Plus", "1"))
        self.assertNotIn("JANE", repr(rows))


if __name__ == "__main__":
    unittest.main()
