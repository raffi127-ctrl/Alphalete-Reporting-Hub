import datetime as dt
import unittest

from automations.nds_metrics import order_log_tab as T

TODAY = dt.date(2026, 10, 29)


def line(**kw):
    base = {"rep": "YAHIR LOPEZ", "customer": "JOHN DOE", "order_date": "10/24/2026",
            "dsi": "DSI123", "wireless_order": "WO555", "ban": "BAN9", "line_no": "1",
            "line_type": "New", "device": "945-392-8474", "line_number": "Smartphone",
            "line_phone": "iPhone 16", "plan": "Unlimited",
            "line_status": "Shipped", "ship_date": "10/25/2026", "delivered": "", "port_status": ""}
    base.update(kw)
    return base


class Rows(unittest.TestCase):
    def test_row_shape_and_week_ending(self):
        r = T.line_row(line(), "10/29/2026")
        self.assertEqual(len(r), len(T.HEADERS))
        self.assertEqual(r[T._COL["Week Ending"]], "10/25/2026")     # Sat 10/24 -> Sun 10/25
        self.assertEqual(r[T._COL["Rep"]], "Yahir Lopez")
        self.assertEqual(r[T._COL["Last Updated"]], "10/29/2026")
        self.assertEqual(r[T._COL["Notes"]], "")
        self.assertEqual(r[T._COL["Being worked on"]], "")
        self.assertEqual(r[T._COL["Delivered Message Sent"]], "")
        self.assertEqual(T.HEADERS[19], "Delivered Message Sent")   # column T on the live tab (S until 11/9)
        self.assertEqual(r[T._COL["Phone #"]], "945-392-8474")        # the feed's "device" = Line Number cell
        self.assertEqual(r[T._COL["Device"]], "iPhone 16")            # the model, feed's "line_phone"
        self.assertEqual(r[T._COL["Plan"]], "Unlimited")

    def test_old_tab_layout_remaps_by_header(self):
        # the live tab before 11/9: no "Phone #", "Device" held the number, column S = Delivered Message Sent
        old_hdr = ["Week Ending", "Rep", "Customer", "Order Date", "DSI #", "Wireless Order #", "BAN",
                   "Line", "Type", "Device", "Plan", "Line Status", "Ship Date", "Delivered", "Port Status",
                   "Last Updated", "Notes", "Being worked on", "Delivered Message Sent"]
        old_row = ["10/25/2026", "Yahir Lopez", "John Doe", "10/24/2026", "DSI123", "WO555", "BAN9",
                   "2", "Port", "945-392-8474", "Unlimited", "Shipped", "10/25/2026", "", "",
                   "10/29/2026", "called 10/28", "Yes", "Yes"]
        r = T.remap(old_row, old_hdr)
        self.assertEqual(len(r), len(T.HEADERS))
        self.assertEqual(r[T._COL["Phone #"]], "945-392-8474")
        self.assertEqual(r[T._COL["Device"]], "")
        self.assertEqual(r[T._COL["Notes"]], "called 10/28")
        self.assertEqual(r[T._COL["Being worked on"]], "Yes")
        self.assertEqual(r[T._COL["Delivered Message Sent"]], "Yes")
        # through merge: line 2 absent from today's feed is kept with its typed columns in place
        out = T.merge([old_row], [line()], today=TODAY, existing_header=old_hdr)
        by_key = {T._key(x): x for x in out["rows"]}
        kept = by_key[("wo", "wo555", "2")]
        self.assertEqual(kept[T._COL["Delivered Message Sent"]], "Yes")
        self.assertEqual(kept[T._COL["Notes"]], "called 10/28")
        self.assertEqual(kept[T._COL["Phone #"]], "945-392-8474")
        # today's header round-trips unchanged
        fresh = out["rows"][0]
        self.assertEqual(T.remap(fresh, T.HEADERS), list(fresh))

    def test_html_entities_are_unescaped(self):
        r = T.line_row(line(plan="AT&amp;T Premium", customer="O&#39;BRIEN"), "x")
        self.assertEqual(r[T._COL["Plan"]], "AT&T Premium")
        self.assertEqual(r[T._COL["Customer"]], "O'Brien")

    def test_key_fallbacks(self):
        self.assertEqual(T._key(T.line_row(line(), "x"))[0], "wo")
        self.assertEqual(T._key(T.line_row(line(wireless_order=""), "x"))[0], "dsi")
        self.assertEqual(T._key(T.line_row(line(wireless_order="", dsi=""), "x"))[0], "cust")


class Usable(unittest.TestCase):
    def test_headerless_feed_is_refused(self):
        bare = [{"line_no": "1", "line_type": "New", "line_status": "Shipped"}] * 5
        self.assertFalse(T.usable([], bare))
        self.assertFalse(T.usable([{"customer": "X"}], bare))
        self.assertTrue(T.usable([{"customer": "X"}], [line(), line(line_no="2")]))


class Merge(unittest.TestCase):
    def test_new_changed_kept_aged_and_notes(self):
        first = T.merge([], [line(), line(line_no="2", line_status="Active")], today=TODAY)
        self.assertEqual((first["added"], first["changed"], first["aged_out"]), (2, 0, 0))
        rows = [list(r) for r in first["rows"]]
        rows[0][T._COL["Notes"]] = "called 10/28"            # Carlos types a note on the first row
        rows[0][T._COL["Being worked on"]] = "Yes"
        rows[0][T._COL["Delivered Message Sent"]] = "Yes"      # rc_contact_sync.delivered marked it
        noted_key = T._key(rows[0])
        # next morning: line 1 activates, line 2 missing from the feed (kept), an old line ages out
        later = TODAY + dt.timedelta(days=1)
        old = line(order_date="08/01/2026", wireless_order="WOOLD", line_no="1")
        second = T.merge(rows, [line(line_status="Active"), old], today=later)
        self.assertEqual(second["aged_out"], 0)              # old one never entered the window
        self.assertEqual(second["changed"], 1)
        by_key = {T._key(r): r for r in second["rows"]}
        self.assertEqual(len(by_key), 2)                      # line 2 kept though absent today
        self.assertEqual(by_key[noted_key][T._COL["Notes"]], "called 10/28")
        self.assertEqual(by_key[noted_key][T._COL["Being worked on"]], "Yes")
        self.assertEqual(by_key[noted_key][T._COL["Delivered Message Sent"]], "Yes")
        l1 = by_key[("wo", "wo555", "1")]
        self.assertEqual(l1[T._COL["Line Status"]], "Active")
        self.assertEqual(l1[T._COL["Last Updated"]], "10/30/2026")
        l2 = by_key[("wo", "wo555", "2")]
        self.assertEqual(l2[T._COL["Last Updated"]], "10/29/2026")   # untouched -> stamp kept

    def test_unchanged_line_keeps_its_stamp(self):
        first = T.merge([], [line()], today=TODAY)
        second = T.merge(first["rows"], [line()], today=TODAY + dt.timedelta(days=3))
        self.assertEqual(second["changed"], 0)
        self.assertEqual(second["rows"][0][T._COL["Last Updated"]], "10/29/2026")

    def test_ages_out_by_order_date(self):
        stale = T.line_row(line(order_date="08/01/2026", wireless_order="WOOLD"), "08/02/2026")
        res = T.merge([stale], [line()], today=TODAY)
        self.assertEqual(res["aged_out"], 1)
        self.assertEqual(len(res["rows"]), 1)

    def test_existing_rows_without_a_line_number_are_dropped(self):
        bad = T.line_row(line(line_no="", customer="Luis Martinez"), "10/29/2026")
        res = T.merge([bad], [line()], today=TODAY)
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0][T._COL["Line"]], "1")

    def test_protected(self):
        self.assertNotIn(T.TAB, T.PROTECTED_TABS)


if __name__ == "__main__":
    unittest.main()
