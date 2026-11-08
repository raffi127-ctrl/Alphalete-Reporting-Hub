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


class Churn(unittest.TestCase):
    def test_disconnected_over_activated_by_days_since_activation(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        h = list(T.HEADER)
        i = {c: h.index(c) for c in h}

        def line(rep, status, active):
            r = [""] * len(h)
            r[i["Rep"]], r[i["DTR Status"]], r[i["DTR Active Date"]] = rep, status, active
            return r
        rows = [line("A B", "Posted", "11/01/2026"), line("A B", "Disconnected", "11/02/2026"),
                line("A B", "Posted", "10/01/2026"), line("C D", "Submitted", "")]
        seen = {}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch("automations.b2b_metrics.rep_boards.render_table_png",
                           side_effect=lambda t, st, cols, table, out: seen.update(table=table) or out):
            T.churn("X", h, rows, dt.date(2026, 11, 7), Path(td))
        office = seen["table"][0][3]
        self.assertEqual((office["0-30 Day"]["disc"], office["0-30 Day"]["act"]), ("1", "2"))
        self.assertEqual((office["31-60 Day"]["disc"], office["31-60 Day"]["act"]), ("0", "1"))
        self.assertEqual([r[0] for r in seen["table"][1:]], ["A B"])   # never-activated rep left off


class Comp(unittest.TestCase):
    def test_line_pay_on_the_comp_grid(self):
        from automations.verizon_office import comp as C
        port = {"status": "Posted", "port_new": True, "autopay": True, "premium": True, "protect": False}
        self.assertEqual(C.line_pay(port, 4), 190 + 60 + 35)
        self.assertEqual(C.line_pay(dict(port, port_new=False, autopay=False, premium=False), 4), 25)
        self.assertEqual(C.line_pay(dict(port, status="Disconnected"), 4), 0)

    def test_weekly_tiers(self):
        from automations.verizon_office import comp as C
        self.assertEqual([C.weekly_tier(n)[1] for n in (3, 4, 6, 7, 9)], [0, 30, 50, 75, 110])
        self.assertEqual(C.next_weekly(4), ("T2", 1, 50))
        self.assertIsNone(C.next_weekly(12))


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
