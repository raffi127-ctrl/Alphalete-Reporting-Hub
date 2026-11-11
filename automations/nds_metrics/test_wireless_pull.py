"""SaraPlus Wireless Resolution feed parser (nds_metrics.wireless_pull).

11/11/2026: SaraPlus re-cut the order grid -- one leading cell instead of
two, and ICD Company ID / ICD Owner / Employer inserted after Salesperson --
and the positional read found 0 orders for 316 lines all morning (the NDS
Order Log tab was left as it was). Orders are now read by the grid header,
with the positional read as the fallback.

  python -m unittest automations.nds_metrics.test_wireless_pull
"""
import unittest

from automations.nds_metrics import wireless_pull as WP


def _tr(cells):
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


OLD_HDR = ["", "", "Customer Name", "Contact Phone", "Order Number", "Order Date",
           "Wireless Order Number", "Wireless Account Number", "Lines", "Salesperson",
           "Dealer Name", "Dealer Code", "Order Status"]
OLD_ROW = ["", "", "JANE D", "214-555-0100", "DSI1", "11/10/2026", "99-1", "BAN1", "2",
           "Ana Lopez", "ALPHALETE", "D1", "Approved"]
NEW_HDR = ["", "Customer Name", "Contact Phone", "Order Number", "Order Date",
           "Wireless Order Number", "Wireless Account Number", "Lines", "Salesperson",
           "ICD Company ID", "ICD Owner", "Employer", "Dealer Name", "Dealer Code",
           "Order Status", "Submitted"]
NEW_ROW = ["", "CLAUDIA MURILLO", "682-414-0118", "DSI280183900", "10/19/2026",
           "99-617030141596672", "177145276543", "2", "Jose Manuel Pimentel Lugo",
           "11633D2D", "CARLOS HIDALGO", "ALPHALETE SPECIALIZED", "Dealer", "D1",
           "Approved", "x"]
LINE_HDR = ["", "Line", "Line Type", "Device Type", "Line Number", "Phone", "Plan",
            "Line Status", "Est. Shipping Range", "Ship Date", "Delieverd Date", "Port Status"]
LINE_ROW = ["1", "port", "Phone", "iPhone 18", "2145550101", "Unlimited", "Active", "",
            "11/11/2026", "", "Approved"]


class OrderRows(unittest.TestCase):
    def _parse(self, *rows):
        html = "<table>" + "".join(_tr(r) for r in rows) + "</table>"
        logs = []
        orders, lines = WP.parse(html.encode(), log=logs.append)
        return orders, lines, logs

    def test_new_grid_reads_by_header(self):
        orders, lines, _ = self._parse(NEW_HDR, NEW_ROW, LINE_HDR, LINE_ROW)
        self.assertEqual(len(orders), 1)
        o = orders[0]
        self.assertEqual(o["customer"], "CLAUDIA MURILLO")
        self.assertEqual(o["dsi"], "DSI280183900")
        self.assertEqual(o["order_date"], "10/19/2026")
        self.assertEqual(o["ban"], "177145276543")
        self.assertEqual(o["rep"], "Jose Manuel Pimentel Lugo")
        self.assertEqual(o["order_status"], "Approved")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["rep"], "Jose Manuel Pimentel Lugo")   # the line carries its order
        self.assertEqual(lines[0]["device"], "iPhone 18")

    def test_old_grid_still_reads(self):
        orders, lines, _ = self._parse(OLD_HDR, OLD_ROW, LINE_HDR, LINE_ROW)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["customer"], "JANE D")
        self.assertEqual(orders[0]["order_status"], "Approved")
        self.assertEqual(lines[0]["customer"], "JANE D")

    def test_new_grid_without_a_header_row_falls_back_to_position(self):
        orders, _lines, _ = self._parse(NEW_ROW, LINE_HDR, LINE_ROW)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["customer"], "CLAUDIA MURILLO")
        self.assertEqual(orders[0]["rep"], "Jose Manuel Pimentel Lugo")

    def test_calendar_and_pager_rows_are_not_orders(self):
        orders, lines, logs = self._parse(
            ["October 2026", "S", "M", "T", "W", "T", "F", "S"],
            ["42", "11", "12", "13", "14", "15", "16", "17", "a", "b", "c", "d", "e"],
            LINE_HDR, LINE_ROW)
        self.assertEqual(orders, [])
        self.assertEqual(len(lines), 1)
        self.assertTrue(any("no-order-row sample" in x for x in logs))   # the diagnostic fires


if __name__ == "__main__":
    unittest.main()
