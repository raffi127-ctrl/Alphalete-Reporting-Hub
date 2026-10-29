import datetime as dt
import unittest

from automations.rc_contact_sync import delivered as D

TODAY = dt.date(2026, 10, 29)
HDR = ["Week Ending", "Rep", "Customer", "Order Date", "DSI #", "Wireless Order #", "BAN",
       "Line", "Type", "Device", "Plan", "Line Status", "Ship Date", "Delivered", "Port Status",
       "Last Updated", "Notes", "Being worked on", "Delivered Message Sent"]


def row(**kw):
    base = {"Week Ending": "10/25/2026", "Rep": "Aaron De La Torre", "Customer": "Jerry Jackson",
            "Order Date": "10/24/2026", "DSI #": "DSI1", "Wireless Order #": "99-1", "BAN": "B1",
            "Line": "1", "Type": "Port", "Device": "945-392-8474", "Plan": "AT&T Premium 2.0",
            "Line Status": "Delivered", "Ship Date": "10/26/2026", "Delivered": "10/28/2026",
            "Port Status": "", "Last Updated": "10/29/2026", "Notes": "", "Being worked on": "",
            "Delivered Message Sent": ""}
    base.update(kw)
    return [base[h] for h in HDR]


class PickTargets(unittest.TestCase):
    def test_one_text_per_order_only_delivered_lines(self):
        rows = [row(Line="1"), row(Line="2", **{"Line Status": "Active"}),
                row(Line="3", **{"Line Status": "Shipped"}), row(Line="4")]
        t = D.pick_targets(HDR, rows, {}, today=TODAY)
        self.assertEqual(len(t), 1)
        self.assertEqual([l["line"] for l in t[0]["lines"]], ["1", "4"])
        self.assertEqual([l["sheet_row"] for l in t[0]["lines"]], [2, 5])
        self.assertEqual(t[0]["customer"], "Jerry Jackson")

    def test_status_word_not_date_column(self):
        # a Port line whose Delivered DATE is junk but whose status is Active: left alone
        rows = [row(**{"Line Status": "Active", "Delivered": "3/17/2025"})]
        self.assertEqual(D.pick_targets(HDR, rows, {}, today=TODAY), [])
        # and a Delivered status with an empty date still counts
        rows = [row(**{"Line Status": "DELIVERED", "Delivered": ""})]
        self.assertEqual(len(D.pick_targets(HDR, rows, {}, today=TODAY)), 1)

    def test_already_sent_skipped_by_column_s_or_state(self):
        rows = [row(Line="1", **{"Delivered Message Sent": "Yes"}), row(Line="2")]
        t = D.pick_targets(HDR, rows, {}, today=TODAY)
        self.assertEqual([l["line"] for l in t[0]["lines"]], ["2"])
        state = {D.line_key("99-1", "2"): {"at": "x"}}
        self.assertEqual(D.pick_targets(HDR, rows, state, today=TODAY), [])

    def test_two_customers_two_targets_grouped_by_order(self):
        rows = [row(), row(Customer="Jose Deleon", **{"Wireless Order #": "99-2", "DSI #": "DSI2"}),
                row(Line="2", Customer="Jose Deleon", **{"Wireless Order #": "99-2", "DSI #": "DSI2"})]
        t = D.pick_targets(HDR, rows, {}, today=TODAY)
        self.assertEqual([x["customer"] for x in t], ["Jerry Jackson", "Jose Deleon"])
        self.assertEqual(len(t[1]["lines"]), 2)

    def test_old_orders_age_out(self):
        rows = [row(**{"Order Date": "09/01/2026"})]
        self.assertEqual(D.pick_targets(HDR, rows, {}, today=TODAY), [])

    def test_header_resolved_not_positional(self):
        shuffled = list(reversed(HDR))
        rows = [[dict(zip(HDR, row()))[h] for h in shuffled]]
        t = D.pick_targets(shuffled, rows, {}, today=TODAY)
        self.assertEqual(t[0]["customer"], "Jerry Jackson")

    def test_missing_column_s_refuses(self):
        hdr = HDR[:-1]
        with self.assertRaises(RuntimeError):
            D.pick_targets(hdr, [row()[:-1]], {}, today=TODAY)


class Phone(unittest.TestCase):
    def test_match_by_wireless_order_then_dsi(self):
        custs = [{"wireless_order": "99-1", "order_id": "DSI1", "phone": "214-555-0001"},
                 {"wireless_order": "", "order_id": "DSI9", "phone": "214-555-0009"}]
        self.assertEqual(D.customer_phone({"wireless_order": "99-1", "dsi": "x"}, custs), "214-555-0001")
        self.assertEqual(D.customer_phone({"wireless_order": "", "dsi": "DSI9"}, custs), "214-555-0009")
        self.assertEqual(D.customer_phone({"wireless_order": "99-7", "dsi": "DSI7"}, custs), "")


class Text(unittest.TestCase):
    def test_is_carlos_wording(self):
        self.assertTrue(D.TEXT.startswith("Hello! I see that your device(s) have been delivered!"))
        self.assertIn("auto-activate within 24hrs", D.TEXT)
        self.assertTrue(D.TEXT.endswith("please let me know!"))


if __name__ == "__main__":
    unittest.main()
