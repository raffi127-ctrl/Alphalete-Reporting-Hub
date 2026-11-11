import datetime as dt
import unittest

from automations.nds_metrics import att_order_status as A

TODAY = dt.date(2026, 11, 11)
HDR = ["Week Ending", "Rep", "Customer", "Zip", "Email", "Order Date", "DSI #",
       "Wireless Order #", "BAN", "Line", "Type", "Phone #", "Device", "Plan",
       "Line Status", "Ship Date", "Shipping Notes", "Delivered", "Activation Date", "Port Status",
       "Last Updated", "Notes", "Being worked on", "Delivered Message Sent"]


def row(**kw):
    base = {h: "" for h in HDR}
    base.update({"Rep": "Jacob Isaiah Ortega", "Customer": "Rajeshkanna Chandrakasan",
                 "Zip": "75063", "Email": "raj@example.com", "Order Date": "10/20/2026",
                 "DSI #": "DSI280405775", "Wireless Order #": "99-717053512695236",
                 "Line": "2", "Line Status": "Shipped", "Ship Date": "10/21/2026"})
    base.update(kw)
    return [base[h] for h in HDR]


class StaleOrders(unittest.TestCase):
    def test_shipped_three_days_with_no_delivered_date_is_stale(self):
        out = A.stale_orders(HDR, [row()], today=TODAY, days=3)
        self.assertEqual(len(out), 1)
        o = out[0]
        self.assertEqual((o["order"], o["zip"], o["email"], o["why"]),
                         ("99-717053512695236", "75063", "raj@example.com", ""))
        self.assertEqual(o["lines"][0]["row"], 2)          # sheet row: header is 1

    def test_every_shipped_line_by_default_even_without_a_ship_date(self):
        # 11/11 pm: "whenever something is shipped, you're always checking the
        # status updates once a day" -- no age threshold, no ship date needed
        self.assertEqual(len(A.stale_orders(HDR, [row(**{"Ship Date": "11/09/2026"})], today=TODAY)), 1)
        self.assertEqual(len(A.stale_orders(HDR, [row(**{"Ship Date": ""})], today=TODAY)), 1)
        self.assertEqual(A.stale_orders(HDR, [row(Delivered="10/26/2026")], today=TODAY), [])
        for st in ("Active", "Delivered", "Pending Shipment", "Cancelled", ""):
            self.assertEqual(A.stale_orders(HDR, [row(**{"Line Status": st})], today=TODAY), [], st)
        # with --days 3: exactly 3 days old counts, 2 does not, undated not
        self.assertEqual(len(A.stale_orders(HDR, [row(**{"Ship Date": "11/08/2026"})], today=TODAY, days=3)), 1)
        self.assertEqual(A.stale_orders(HDR, [row(**{"Ship Date": "11/09/2026"})], today=TODAY, days=3), [])
        self.assertEqual(A.stale_orders(HDR, [row(**{"Ship Date": ""})], today=TODAY, days=3), [])

    def test_missing_zip_or_email_is_listed_as_blocked(self):
        out = A.stale_orders(HDR, [row(Email="")], today=TODAY)
        self.assertEqual(out[0]["why"], "no email on the tab")
        out = A.stale_orders(HDR, [row(Zip="", Email="")], today=TODAY)
        self.assertEqual(out[0]["why"], "no zip / email on the tab")

    def test_lines_group_by_order_and_zip_apostrophe_dropped(self):
        rows = [row(Line="2", Zip="'07030"), row(Line="3", Zip="'07030"),
                row(Line="1", **{"Wireless Order #": "99-2", "Customer": "Other"})]
        out = A.stale_orders(HDR, rows, today=TODAY)
        self.assertEqual([o["order"] for o in out], ["99-2", "99-717053512695236"])
        self.assertEqual(out[1]["zip"], "07030")
        self.assertEqual([l["line"] for l in out[1]["lines"]], ["2", "3"])

    def test_lines_carry_the_shipping_notes_cell_not_notes(self):
        out = A.stale_orders(HDR, [row(**{"Shipping Notes": "11/10 AT&T: x", "Notes": "hand note"})], today=TODAY)
        self.assertEqual(out[0]["lines"][0]["notes"], "11/10 AT&T: x")

    def test_header_resolved(self):
        shuffled = list(reversed(HDR))
        r = dict(zip(HDR, row()))
        out = A.stale_orders(shuffled, [[r[h] for h in shuffled]], today=TODAY)
        self.assertEqual(out[0]["customer"], "Rajeshkanna Chandrakasan")


PAGE = """Skip Navigation
Order status
Order 99-717053512695236
Shipped
Your order shipped on Oct 21, 2026 and is on its way.
Estimated delivery: Nov 13, 2026
Carrier: UPS
Tracking number 1Z999AA10123456784
Track your package
Feedback
"""


DETAILS = """Look up another order
Print
My order details
Ordered on:
Tue, Oct 20, 2026
Order:
99-717053512695236
Shipping address:
Sign in to see
Wireless order
Order status
Number of items: 4
Shipped on: Wed, Oct 21, 2026
Ordered
Shipped
Delivered
Shipped
Your order is on the way! Check the tracking info to confirm delivery details.
Line 4: xxx.xxx.4914
Apple iPhone 18 Pro - 256GB - Burgundy
Device protection:Not enrolled | Learn more
FedEx tracking:879024018564
Shop again
Shipped on: Mon, Nov 2, 2026
Your order is on the way! Check the tracking info to confirm delivery details.
Line 1: xxx.xxx.5740
FedEx tracking:879615850332
"""


class Summaries(unittest.TestCase):
    def test_real_details_page(self):
        # Rajeshkanna's page, read by hand on 11/11
        s = A.summarize(DETAILS)
        self.assertFalse(s["failed"])
        self.assertIn("Shipped on: Wed, Oct 21, 2026", s["lines"])
        self.assertIn("Your order is on the way! Check the tracking info to confirm delivery details.", s["lines"])
        self.assertEqual(s["trackings"], ["879024018564", "879615850332"])
        self.assertNotIn("Shipped", s["lines"])
        note = A.note_text(s, TODAY, ["FedEx 879024018564: returning to the shipper"])
        self.assertIn("tracking 879024018564; tracking 879615850332; FedEx 879024018564: returning", note)
        self.assertNotIn("FedEx tracking:", note)
        self.assertTrue(A.DETAILS_URL.startswith("https://www.att.com/acctmgmt/order/details?"))


    def test_status_lines_and_tracking(self):
        s = A.summarize(PAGE)
        self.assertFalse(s["failed"])
        self.assertEqual(s["tracking"], "1Z999AA10123456784")
        self.assertIn("Your order shipped on Oct 21, 2026 and is on its way.", s["lines"])
        self.assertIn("Estimated delivery: Nov 13, 2026", s["lines"])
        self.assertNotIn("Feedback", s["lines"])
        note = A.note_text(s, TODAY)
        self.assertTrue(note.startswith("11/11 AT&T: "))
        self.assertTrue(note.endswith("tracking 1Z999AA10123456784"))

    def test_lookup_form_itself_is_not_a_status(self):
        # 11/11: the first live run wrote "Check my status; Confirm the status
        # for orders, claims..." -- the lookup form's own words -- on 4 lines
        form = ("Check my status\nSearch as a guest\nFind an order or claim\nOrder or claim\n"
                "ZIP Code\nStart search\nSign in\nView all my orders or claims\n"
                "Confirm the status for orders, claims, store purchases, and returns.\n")
        s = A.summarize(form)
        self.assertTrue(s["failed"])
        self.assertEqual(s["lines"], [])

    def test_not_found_page_fails(self):
        s = A.summarize("We couldn't find an order with that information. Please try again.")
        self.assertTrue(s["failed"])
        self.assertEqual(s["lines"], [])

    def test_same_words_not_noted_twice(self):
        note = A.note_text(A.summarize(PAGE), TODAY)
        self.assertTrue(A.already_noted(note, note))
        yesterday = note.replace("11/11", "11/10")
        self.assertTrue(A.already_noted(yesterday + " | 10/30 texted Taylor", note))
        self.assertFalse(A.already_noted("10/30 texted Taylor", note))
        self.assertFalse(A.already_noted(note.replace("Nov 13", "Nov 14"), note))


if __name__ == "__main__":
    unittest.main()
