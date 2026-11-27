import datetime as dt
import unittest

from automations.nds_metrics import att_order_status as A

TODAY = dt.date(2026, 11, 11)
HDR = ["Week Ending", "Rep", "Customer", "Zip", "Email", "Order Date", "DSI #",
       "Wireless Order #", "BAN", "Line", "Type", "Phone #", "Device", "Plan",
       "Line Status", "Ship Date", "Shipping Notes", "Delivered", "Activation Date", "Port Status",
       "Last Updated", "Notes", "Being worked on", "Delivered Message Sent", "Shipping Status"]


def row(**kw):
    base = {h: "" for h in HDR}
    base.update({"Rep": "Jacob Isaiah Ortega", "Customer": "Rajeshkanna Chandrakasan",
                 "Zip": "75063", "Email": "raj@example.com", "Order Date": "10/20/2026",
                 "DSI #": "DSI280405775", "Wireless Order #": "99-717053512695236",
                 "Line": "2", "Line Status": "Shipped", "Ship Date": "10/21/2026", "Phone #": "817-673-3727"})
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


UPS_PAGE = """My order details
Ordered on:
Mon, Nov 9, 2026
Order:
99-1
Order status
Number of items: 2
Shipped on: Mon, Nov 9, 2026
Ordered
Shipped
Delivered
Shipped
Your order is on the way! Check the tracking info to confirm delivery details.
Line 1: xxx.xxx.1111
UPS tracking:1ZH4K6532936244036
Delivered on: Tue, Nov 10, 2026
Delivered
Your order arrived\u2014it's unboxing time!
Line 2: xxx.xxx.2222
UPS tracking:1Z1WE1020321622114
Cancel my order
"""


class ShortCell(unittest.TestCase):
    def test_one_line_per_package_newest_first(self):
        sh = A.shipments(UPS_PAGE)
        self.assertEqual([x["kind"] for x in sh], ["shipped", "delivered"])
        cell = A.short_text(UPS_PAGE, TODAY)
        # UPS is never looked up, so AT&T's word stands and says so; the Nov 10 delivery leads
        self.assertEqual(cell, "11/11: Delivered Nov 10 · UPS …2114 (per AT&T) | Shipped Nov 9, UPS not checked · UPS …4036 (per AT&T)")

    def test_fedex_word_and_date_lead(self):
        # Christopher Cardinal 11/12: AT&T "on the way", FedEx delivered 11/3
        page = "Shipped on: Mon, Nov 2, 2026\nYour order is on the way! Check the tracking info to confirm delivery details.\nLine 1: xxx\nFedEx tracking:879000000001\n"
        cell = A.short_text(page, TODAY, ["FedEx 879000000001: Delivered / Tuesday 11/3/2026 at 2:14 pm / Signed for by: J.DOE"])
        self.assertEqual(cell, "11/11: Delivered Nov 3 · FedEx …0001")
        cell = A.short_text(DETAILS, TODAY, ["FedEx 879024018564: The package couldn't be delivered and is returning to the shipper / Currently in Irving, TX",
                                              "FedEx 879615850332: Your package is still on the way and we\u2019re actively working to get you a new delivery date."])
        self.assertEqual(cell, "11/11: Delayed, shipped Nov 2 · FedEx …0332 | Returning to shipper, could not be delivered · FedEx …8564")

    def test_not_checked_is_said_and_yesterday_survives(self):
        cell = A.short_text(DETAILS, TODAY)
        self.assertEqual(cell, "11/11: Shipped Nov 2, FedEx not checked · FedEx …0332 (per AT&T) | Shipped Oct 21, FedEx not checked · FedEx …8564 (per AT&T)")
        prev = "11/11: Delayed, shipped Nov 2 · FedEx …0332 | Returning to shipper, could not be delivered · FedEx …8564"
        today = "11/12: Shipped Nov 2, FedEx not checked · FedEx …0332 (per AT&T) | Shipped Oct 21, FedEx not checked · FedEx …8564 (per AT&T)"
        self.assertEqual(A.keep_fedex_from(today, prev),
                         "11/12: Delayed, shipped Nov 2 · FedEx …0332 (as of 11/11) | Returning to shipper, could not be delivered · FedEx …8564 (as of 11/11)")
        self.assertEqual(A.keep_fedex_from(today, ""), today)

    def test_no_record_today_does_not_erase_a_real_reading(self):
        prev = "11/11: Delivered Nov 3 · FedEx …8080"
        today = "11/12: Shipped Nov 2, FedEx has no record yet · FedEx …8080"
        self.assertEqual(A.keep_fedex_from(today, prev), "11/12: Delivered Nov 3 · FedEx …8080 (as of 11/11)")
        # but a real reading today replaces a "no record" from yesterday
        self.assertEqual(A.keep_fedex_from("11/12: Delivered Nov 3 · FedEx …8080", today.replace("11/12", "11/11")),
                         "11/12: Delivered Nov 3 · FedEx …8080")

    def test_ordered_only_page(self):
        cell = A.short_text("Ordered on:\nWed, Nov 11, 2026\nOrder:\n99-2\nUPS tracking:1Z1WE1020321622114\n", TODAY)
        self.assertEqual(cell, "11/11: Ordered Nov 11, not shipped yet · UPS …2114")
        self.assertEqual(A.short_text("nothing here", TODAY), "")

    def test_fedex_delivered_read_off_the_page_shape(self):
        # Christopher Cardinal 11/12: FedEx's page = "Delivered" over "Tuesday 11/3/2026 at 2:48 pm"
        page = "Shipped on: Mon, Nov 2, 2026\nYour order is on the way!\nLine 1: xxx\nFedEx tracking:879000000080\n"
        fx = "FedEx 879000000080: Delivered Tuesday 11/3/2026 at 2:48 pm / Signed for by: C.CARDINAL / Irving, TX US"
        self.assertEqual(A.short_text(page, TODAY, [fx]), "11/11: Delivered Nov 3 · FedEx …0080")

    def test_fedex_no_record_is_a_status_not_a_blank(self):
        page = "Shipped on: Mon, Nov 9, 2026\nYour order is on the way!\nLine 1: xxx\nFedEx tracking:879000000300\n"
        cell = A.short_text(page, TODAY, ["FedEx 879000000300: No record at FedEx yet (label not scanned)"])
        self.assertEqual(cell, "11/11: Shipped Nov 9, FedEx has no record yet · FedEx …0300")
        self.assertTrue(A.FEDEX_NOT_FOUND_RE.search("We can\u2019t find that tracking number. Please check with the shipper"))

    def test_shipping_status_per_line(self):
        # AT&T names the lines in each package ("Line 4: xxx.xxx.4914"); the
        # status cell follows the line's own package
        pk = A.package_lines(DETAILS, TODAY, ["FedEx 879024018564: The package couldn't be delivered and is returning to the shipper",
                                               "FedEx 879615850332: Delivered Tuesday 11/10/2026 at 9:02 am"])
        self.assertEqual(A.line_status(pk, "945-233-4914"), "Returning to shipper")   # line 4 rode …8564
        self.assertEqual(A.line_status(pk, "817-296-5740"), "Delivered Nov 10")      # line 1 rode …0332
        self.assertEqual(A.line_status(pk, "000-000-0000"), "Delivered Nov 10")      # unnamed: newest package
        self.assertEqual(A.line_status(A.package_lines(DETAILS, TODAY), "945-233-4914"), "Not checked")
        self.assertEqual(A.line_status([], "x"), "")
        o = A.stale_orders(HDR, [row(**{"Shipping Status": "Delayed"})], today=TODAY)
        self.assertEqual((o[0]["lines"][0]["status"], o[0]["lines"][0]["phone"]), ("Delayed", "817-673-3727"))

    def test_status_follows_the_final_notes_cell(self):
        body = "11/12: Delivered Nov 3 · FedEx …8080 (as of 11/11)"
        self.assertEqual(A.status_from_clause(body.split(": ", 1)[1]), "Delivered Nov 3 (as of 11/11)")
        self.assertEqual(A.status_from_clause("11/03/2026 at 2:48 pm, shipped Nov 2 · FedEx …8080 (as of 11/12)"),
                         "Delivered Nov 3 (as of 11/12)")
        self.assertEqual(A.status_from_clause("Returning to shipper, could not be delivered · FedEx …8564"), "Returning to shipper")
        self.assertEqual(A.status_from_clause("Shipped Nov 9, FedEx has no record yet · FedEx …0300"), "No record yet")
        self.assertEqual(A.status_from_clause("Shipped Nov 9, UPS not checked · UPS …4036 (per AT&T)"), "Not checked")
        self.assertEqual(A.status_from_clause("Ordered Nov 11, not shipped yet · UPS …2114"), "Not shipped yet")
        pk = A.package_lines(DETAILS, TODAY, ["FedEx 879024018564: The package couldn't be delivered and is returning to the shipper",
                                               "FedEx 879615850332: Delivered Tuesday 11/10/2026 at 9:02 am"])
        body = A.short_text(DETAILS, TODAY, ["FedEx 879024018564: The package couldn't be delivered and is returning to the shipper",
                                             "FedEx 879615850332: Delivered Tuesday 11/10/2026 at 9:02 am"])
        self.assertEqual(A.status_for_line(body, pk, "945-233-4914"), "Returning to shipper")
        self.assertEqual(A.status_for_line(body, pk, "817-296-5740"), "Delivered Nov 10")

    def test_status_sync_follows_notes_without_downgrading(self):
        rows = [row(**{"Shipping Notes": "11/11: Delivered Nov 10 (UPS …4810)", "Shipping Status": "", "Line Status": "Active"}),
                row(**{"Shipping Notes": "11/12: Delivered Nov 10 · FedEx …8491", "Shipping Status": "No record yet"}),
                row(**{"Shipping Notes": "11/12: Shipped Oct 31, FedEx has no record yet · FedEx …0260", "Shipping Status": "Delivered Oct 25"}),
                row(**{"Shipping Notes": "", "Shipping Status": ""}),
                row(**{"Shipping Notes": "11/12: In transit, shipped Nov 9 · FedEx …4300", "Shipping Status": "In transit"})]
        fixes = A.status_sync(HDR, rows)
        self.assertEqual(fixes, [{"row": 2, "status": "Delivered Nov 10"}, {"row": 3, "status": "Delivered Nov 10"}])

    def test_fedex_date_forms(self):
        self.assertEqual(A._fedex_date("Delivered / Tuesday 11/3/2026 at 2:14 pm"), "Nov 3")
        self.assertEqual(A._fedex_date("Delivered / November 3, 2026"), "Nov 3")
        self.assertEqual(A._fedex_date("Currently in Irving, TX"), "")

    def test_detail_note_lists_everything(self):
        s = A.summarize(DETAILS)
        d = A.detail_text(s, TODAY, ["FedEx 879024018564: returning"])
        self.assertTrue(d.startswith("Checked "))
        self.assertIn("AT&T: Shipped on: Wed, Oct 21, 2026", d)
        self.assertIn("FedEx 879024018564: returning", d)


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


class ProbeAnyStatus(unittest.TestCase):
    """11/20: Nelson Martinez's six lines read Pending Shipment while Carlos
    thought the phones had arrived -- the probe looks an order up whatever
    its Line Status says."""

    def test_any_status_picks_a_pending_shipment_order(self):
        import datetime as dt
        hdr = ["Line Status", "Ship Date", "Delivered", "Wireless Order #", "Zip", "Email",
               "Shipping Notes", "Shipping Status", "Customer", "Line", "Phone #", "Rep"]
        rows = [["Pending Shipment", "", "", "99-7", "75040", "a@b.c", "", "", "NELSON M", "1", "206-555-0101", "R"],
                ["Pending Shipment", "", "", "99-7", "75040", "a@b.c", "", "", "NELSON M", "2", "206-555-0102", "R"]]
        self.assertEqual(A.stale_orders(hdr, rows, today=dt.date(2026, 11, 20)), [])
        got = A.stale_orders(hdr, rows, today=dt.date(2026, 11, 20), any_status=True)
        self.assertEqual([(o["order"], len(o["lines"])) for o in got], [("99-7", 2)])


class UntilDelivered(unittest.TestCase):
    """11/27, Carlos: "lets check the status of all orders until they're
    marked delivered. On column Z you need to mark that column with one of
    these Status" -- every line not Delivered yet, whatever its Line Status."""

    def test_open_lines_are_looked_up_until_delivered(self):
        for st in ("Shipped", "Pending Shipment", "Backordered", "BYOD", "Port Approved", ""):
            got = A.stale_orders(HDR, [row(**{"Line Status": st})], today=TODAY, until_delivered=True)
            self.assertEqual(len(got), 1, st)

    def test_active_delivered_cancelled_disconnected_need_no_check(self):
        # "once its active the shipping status doesnt matter ... Cancelled or
        # disconnected same thing"
        for st in ("Active", "Delivered", "Cancelled", "Disconnected", "Returned"):
            self.assertEqual(A.stale_orders(HDR, [row(**{"Line Status": st})], today=TODAY,
                                            until_delivered=True), [], st)

    def test_delivered_status_or_date_stops_the_checks(self):
        self.assertEqual(A.stale_orders(HDR, [row(**{"Shipping Status": "Delivered Nov 9 (as of 11/12)"})],
                                        today=TODAY, until_delivered=True), [])
        self.assertEqual(A.stale_orders(HDR, [row(Delivered="11/09/2026")], today=TODAY, until_delivered=True), [])

    def test_oldest_check_first(self):
        rows = [row(**{"Wireless Order #": "99-B", "Customer": "Pat Newer",
                       "Shipping Notes": "11/10: Shipped Nov 1, on the way"}),
                row(**{"Wireless Order #": "99-C", "Customer": "Pat Older",
                       "Shipping Notes": "11/03: Shipped Nov 1, on the way"}),
                row(**{"Wireless Order #": "99-D", "Customer": "Pat Never", "Line Status": "Pending Shipment"})]
        got = A.stale_orders(HDR, rows, today=TODAY, until_delivered=True)
        self.assertEqual([o["order"] for o in got], ["99-D", "99-C", "99-B"])

    def test_delivered_column_fills_the_status_without_a_lookup(self):
        rows = [row(Delivered="11/25/2026"),
                row(Delivered="11/25/2026", **{"Shipping Status": "Delivered Nov 24"}),
                row()]
        self.assertEqual(A.delivered_from_column(HDR, rows), [{"row": 2, "status": "Delivered Nov 25"}])

    def test_checked_on_reads_the_notes_date(self):
        self.assertEqual(A._checked_on("11/03: Shipped", TODAY), dt.date(2026, 11, 3))
        self.assertEqual(A._checked_on("12/30: Shipped", TODAY), dt.date(2025, 12, 30))
        self.assertEqual(A._checked_on("", TODAY), dt.date.min)
