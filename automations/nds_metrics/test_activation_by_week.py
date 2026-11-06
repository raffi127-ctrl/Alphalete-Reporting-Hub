import datetime as dt
import unittest

from automations.nds_metrics import activation_by_week as AW
from automations.nds_metrics.test_line_revenue import IX, line, order

FRI = dt.date(2026, 11, 6)


class Weeks(unittest.TestCase):
    def test_week_ending_is_sunday(self):
        self.assertEqual(AW.week_ending(dt.date(2026, 10, 19)), dt.date(2026, 10, 25))
        self.assertEqual(AW.week_ending(dt.date(2026, 10, 25)), dt.date(2026, 10, 25))
        self.assertEqual(AW.week_ending(dt.date(2026, 10, 26)), dt.date(2026, 11, 1))

    def test_rows(self):
        o1 = order("A", "DSI1", order_date="10/20/2026", **{"Wireless Status": "Active", "Wireless Line Count": "2", "Port Line Count": "2"})
        o2 = order("B", "DSI2", order_date="10/22/2026", **{"Wireless Status": "Shipped - Delivered", "Wireless Line Count": "1", "Port Line Count": "1"})
        o3 = order("C", "DSI3", order_date="10/28/2026", **{"Wireless Status": "Partial - Active/Shipped", "Wireless Line Count": "3", "Port Line Count": "3"})
        air = order("D", "DSI4", order_date="10/28/2026", **{"Internet Package": "AT&T Internet Air", "Internet Status": "Active"})
        lines = [line("DSI1", 1, "Active", tn="1110000001"), line("DSI1", 2, "Disconnected", tn="1110000002"),
                 line("DSI2", 1, "Delivered", tn="1110000003")]
        state = {"1110000002": {"first_active": "2026-10-22", "src": "order"}}
        rows = AW.rows_for((IX, [o1, o2, o3, air], None), lines, state, FRI)
        self.assertEqual([r["we"] for r in rows], [dt.date(2026, 10, 25), dt.date(2026, 11, 1)])
        w1, w2 = rows
        self.assertEqual((w1["orders"], w1["lines"], w1["activated"], w1["churned"], w1["pending"], w1["orders_act"]),
                         (2, 3, 2, 1, 1, 1))
        self.assertAlmostEqual(w1["rate"], 2 / 3)
        # order off the report: Partial = one line activated, the rest pending
        self.assertEqual((w2["orders"], w2["lines"], w2["activated"], w2["pending"], w2["orders_act"]), (1, 3, 1, 2, 1))
        self.assertFalse(w1["current"])
        self.assertTrue(AW.rows_for((IX, [order("E", "DSI9", order_date="11/05/2026", **{"Wireless Status": "Pending Shipment", "Wireless Line Count": "1"})], None), [], {}, FRI)[0]["current"])

    def test_per_rep_cells_and_columns(self):
        o1 = order("Nick", "DSI1", order_date="10/20/2026", **{"Wireless Status": "Active", "Wireless Line Count": "2", "Port Line Count": "2"})
        o2 = order("Jacob", "DSI2", order_date="10/22/2026", **{"Wireless Status": "Shipped - Delivered", "Wireless Line Count": "1", "Port Line Count": "1"})
        lines = [line("DSI1", 1, "Active", tn="2220000001"), line("DSI1", 2, "Shipped", tn="2220000002"),
                 line("DSI2", 1, "Delivered", tn="2220000003")]
        weeks, data = AW.aggregate((IX, [o1, o2], None), lines, {}, FRI)
        self.assertEqual(weeks, [dt.date(2026, 10, 25)])
        self.assertEqual(data["Nick"][weeks[0]]["activated"], 1)
        self.assertEqual(data["Jacob"][weeks[0]]["activated"], 0)
        self.assertEqual(data[AW.TOTAL][weeks[0]]["lines"], 3)
        self.assertEqual(AW._color(dt.date(2026, 10, 25), FRI, 0.8), "Green")
        self.assertEqual(AW._color(dt.date(2026, 10, 25), FRI, 0.5), "Red")


if __name__ == "__main__":
    unittest.main()
