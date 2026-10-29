import datetime as dt
import unittest

from automations.nds_metrics import order_log_tab as T

TODAY = dt.date(2026, 10, 29)


def line(**kw):
    base = {"rep": "YAHIR LOPEZ", "customer": "JOHN DOE", "order_date": "10/24/2026",
            "dsi": "DSI123", "wireless_order": "WO555", "ban": "BAN9", "line_no": "1",
            "line_type": "New", "device": "iPhone 16", "plan": "Unlimited",
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

    def test_key_fallbacks(self):
        self.assertEqual(T._key(T.line_row(line(), "x"))[0], "wo")
        self.assertEqual(T._key(T.line_row(line(wireless_order=""), "x"))[0], "dsi")
        self.assertEqual(T._key(T.line_row(line(wireless_order="", dsi=""), "x"))[0], "cust")


class Merge(unittest.TestCase):
    def test_new_changed_kept_aged_and_notes(self):
        first = T.merge([], [line(), line(line_no="2", line_status="Active")], today=TODAY)
        self.assertEqual((first["added"], first["changed"], first["aged_out"]), (2, 0, 0))
        rows = [list(r) for r in first["rows"]]
        rows[0][T._COL["Notes"]] = "called 10/28"            # Carlos types a note on the first row
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

    def test_protected(self):
        self.assertNotIn(T.TAB, T.PROTECTED_TABS)


if __name__ == "__main__":
    unittest.main()
