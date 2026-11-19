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


class Windows(unittest.TestCase):
    def test_31_days_become_four_disjoint_windows(self):
        # 11/12: the grid shows one page of 100 orders; a 31-day window passed
        # 100 on 11/10 and the newest orders fell off every pull since
        import datetime as dt
        w = WP.windows(dt.date(2026, 10, 12), dt.date(2026, 11, 12))
        self.assertEqual(w[0], (dt.date(2026, 10, 12), dt.date(2026, 10, 21)))
        self.assertEqual(w[-1], (dt.date(2026, 11, 11), dt.date(2026, 11, 12)))
        self.assertEqual(len(w), 4)
        for (a, b), (c, d) in zip(w, w[1:]):
            self.assertEqual(c, b + dt.timedelta(days=1))
            self.assertLessEqual((b - a).days, 9)

    def test_two_joined_documents_parse_in_order(self):
        import pathlib
        one = pathlib.Path(__file__).with_name("test_wireless_pull.py").read_bytes()  # any bytes: parse must not choke
        two = b"\n<!-- window -->\n".join([one, one])
        o, l = WP.parse(two, log=lambda *a, **k: None)
        self.assertEqual((o, l), ([], []))


if __name__ == "__main__":
    unittest.main()


class FeedTrace(unittest.TestCase):
    """11/19: the tab showed a customer with three extra lines that belonged
    to another order. trace() is the read-only look at how a day's feed files
    its line rows -- the order's own 'Lines' count is the check."""

    def test_trace_flags_an_order_holding_more_lines_than_it_says(self):
        import datetime as dt
        import pathlib
        import tempfile
        other = list(NEW_ROW)
        other[1], other[3], other[5], other[7] = "JOHN ROE", "DSI2", "99-2", "1"
        line2 = list(LINE_ROW)
        line2[0], line2[4] = "2", "2145550102"
        # JOHN ROE says 1 line but two rows follow him; CLAUDIA says 2 and has 1
        html = "<table>" + "".join(_tr(r) for r in (NEW_HDR, NEW_ROW, LINE_HDR, LINE_ROW,
                                                    other, LINE_HDR, LINE_ROW, line2)) + "</table>"
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "feed.html"
            f.write_text(html)
            real, WP.cached = WP.cached, lambda day: f
            try:
                logs = []
                self.assertEqual(WP.trace(dt.date(2026, 11, 19), "roe", log=logs.append), 0)
            finally:
                WP.cached = real
        text = "\n".join(logs)
        self.assertIn("2 order(s), 3 line(s)", text)
        self.assertIn("orders whose line rows != their 'Lines' count: 2", text)
        self.assertIn("DUP 2145550101", text)                 # the same number under both orders
        self.assertIn("HIT #001 JOHN ROE", text)
        self.assertIn("near #000 CLAUDIA MURILLO", text)


class ResolveOrderRows(unittest.TestCase):
    """11/19: SaraPlus marks an order that needs fixing with a 'Resolve Order'
    button cell in front of the customer. The row was read as a line with no
    number and thrown away, so the order's lines were filed under the customer
    above it (Danzell Vaughn showed Osman Justiniano's 'Porting Issue')."""
    RESOLVE = ["", "Resolve Order", "OSMAN J", "817-555-0100", "DSI9", "11/14/2026", "99-9", "BAN9", "2",
               "Stefany Z", "11633D2D", "CARLOS HIDALGO", "ALPHALETE SPECIALIZED", "Dealer", "D1",
               "Approved", "x"]

    def _parse(self, *rows):
        html = "<table>" + "".join(_tr(r) for r in rows) + "</table>"
        logs = []
        orders, lines = WP.parse(html.encode(), log=logs.append)
        return orders, lines, logs

    def _line(self, no, number, status="Port Approved"):
        r = list(LINE_ROW)
        r[0], r[4], r[6] = no, number, status
        return r

    def test_resolve_order_row_starts_its_own_order(self):
        orders, lines, _ = self._parse(
            NEW_HDR, NEW_ROW, LINE_HDR, self._line("1", "2145550101", "Delivered"),
            self.RESOLVE, LINE_HDR, self._line("1", "8175550101"), self._line("2", "8175550102", "Porting Issue"))
        self.assertEqual([o["customer"] for o in orders], ["CLAUDIA MURILLO", "OSMAN J"])
        self.assertTrue(orders[1]["resolve"])
        self.assertEqual((orders[1]["dsi"], orders[1]["wireless_order"], orders[1]["rep"], orders[1]["line_count"]),
                         ("DSI9", "99-9", "Stefany Z", "2"))
        self.assertEqual([(l["customer"], l["line_no"], l["line_status"]) for l in lines],
                         [("CLAUDIA MURILLO", "1", "Delivered"), ("OSMAN J", "1", "Port Approved"),
                          ("OSMAN J", "2", "Porting Issue")])

    def test_old_two_cell_grid_resolve_row_reads_by_header(self):
        resolve = ["", "Resolve Order"] + OLD_ROW[2:]
        orders, lines, _ = self._parse(OLD_HDR, resolve, LINE_HDR, LINE_ROW)
        self.assertEqual(orders[0]["customer"], "JANE D")
        self.assertEqual(lines[0]["customer"], "JANE D")

    def test_a_repeated_line_number_is_never_filed_under_the_order_above(self):
        # an order header in a shape nobody has seen yet: its lines must not land on Claudia
        odd = ["?"] * 5
        orders, lines, logs = self._parse(
            NEW_HDR, NEW_ROW, LINE_HDR, self._line("1", "2145550101", "Delivered"),
            odd, LINE_HDR, self._line("1", "8175550101"), self._line("2", "8175550102"),
            self.RESOLVE, LINE_HDR, self._line("1", "8175550103"))
        self.assertEqual([(l["customer"], l["line_no"]) for l in lines],
                         [("CLAUDIA MURILLO", "1"), ("OSMAN J", "1")])
        self.assertTrue(any("2 line row(s) left out" in x for x in logs))
