"""nds_metrics.line_revenue -- the per-line activation revenue core, no IO."""
import datetime as dt
import unittest

from automations.nds_metrics import line_revenue as LR

RATES = {
    "wireless": {"port_nonbyod": {"OOF": 213, "INFP": 193},
                 "port_byod": {"OOF": 188, "INFP": 168},
                 "new_line": 25, "upgrade_voice": 30,
                 "tablet_wearable_nonbyod": 25},
    "addons": {"unlimited_premium": 15, "unlimited_extra": 10},
    "internet_air": {"activation": 93, "auto_bill_pay_bonus": 30},
}
FRI = dt.date(2026, 11, 6)      # last = 10/26..11/1, this = 11/2..11/8

HDR = ["User Name", "Order ID", "Order Date", "Wireless Status",
       "Wireless Active Date", "Wireless Line Count", "Port Line Count",
       "BYOD Line Count", "New Line Count", "Upgrade Line Count",
       "Wireless Cancel Date", "Internet Package", "Internet Status",
       "Internet Install Date", "Internet Cancel Date", "ABP"]
IX = {h: i for i, h in enumerate(HDR)}


def order(rep, oid, **kw):
    r = [""] * len(HDR)
    r[IX["User Name"]] = rep
    r[IX["Order ID"]] = oid
    r[IX["Order Date"]] = kw.pop("order_date", "10/28/2026")
    for k, v in kw.items():
        r[IX[k]] = v
    return r


def line(oid, idx, status, **kw):
    base = {"order_id": oid, "customer": "JOHN DOE", "order_date": "10/28/2026",
            "salesperson": "x", "order_status": "", "line_idx": str(idx),
            "line_type": "Port", "device_type": "Smartphone", "tn": "214555%04d" % idx,
            "device": "iPhone 16", "plan": "AT&T Unlimited Extra",
            "line_status": status, "ship_date": "", "delivered": "", "port_status": ""}
    base.update(kw)
    return base


class Weeks(unittest.TestCase):
    def test_monday_to_sunday(self):
        ls, le, ts, te = LR.week_bounds(FRI)
        self.assertEqual((ls, le), (dt.date(2026, 10, 26), dt.date(2026, 11, 1)))
        self.assertEqual((ts, te), (dt.date(2026, 11, 2), dt.date(2026, 11, 8)))

    def test_monday_rolls_the_week(self):
        ls, le, ts, te = LR.week_bounds(dt.date(2026, 11, 9))
        self.assertEqual((ls, le), (dt.date(2026, 11, 2), dt.date(2026, 11, 8)))

    def test_sunday_belongs_to_the_week_it_ends(self):
        ls, le, ts, te = LR.week_bounds(dt.date(2026, 11, 8))
        self.assertEqual((ts, te), (dt.date(2026, 11, 2), dt.date(2026, 11, 8)))

    def test_label(self):
        self.assertEqual(LR.label(dt.date(2026, 10, 26), dt.date(2026, 11, 1)),
                         "WE 11.1: 10.26 - 11.1")


class Pricing(unittest.TestCase):
    def test_port_byod_new_upgrade_air(self):
        self.assertEqual(LR.price_line(line("o", 1, "Active"), RATES), (213.0, "port"))
        self.assertEqual(LR.price_line(line("o", 1, "Active", device_type="BYOD"), RATES),
                         (188.0, "byod port"))
        self.assertEqual(LR.price_line(line("o", 1, "Active", line_type="BYOD"), RATES)[0], 188.0)
        self.assertEqual(LR.price_line(line("o", 1, "Active", line_type="New"), RATES), (25.0, "new"))
        self.assertEqual(LR.price_line(line("o", 1, "Active", line_type="Upgrade"), RATES), (30.0, "upgrade"))
        self.assertEqual(LR.price_line(line("o", 1, "Active", line_type="AIA"), RATES), (0.0, "air"))

    def test_addon_from_plan(self):
        self.assertEqual(LR.addon_of("AT&T Unlimited Premium PL", RATES), 15.0)
        self.assertEqual(LR.addon_of("AT&T Unlimited Extra EL", RATES), 10.0)
        self.assertEqual(LR.addon_of("Unlimited Starter", RATES), 0.0)

    def test_dates(self):
        self.assertEqual(LR.activation_date({"first_active": "2026-11-02", "src": "live"}),
                         dt.date(2026, 11, 1))
        self.assertEqual(LR.activation_date({"first_active": "2026-10-26", "src": "order"}),
                         dt.date(2026, 10, 26))
        self.assertIsNone(LR.activation_date({}))
        self.assertIsNone(LR.dead_date({"first_dead": "2026-11-05"}, "Active", None))
        self.assertEqual(LR.dead_date({"first_dead": "2026-11-05"}, "Disconnected", None),
                         dt.date(2026, 11, 4))
        self.assertEqual(LR.dead_date({}, "Cancelled", dt.date(2026, 11, 2)),
                         dt.date(2026, 11, 2))

    def test_byod_fallback_marks_unshipped_ports_first(self):
        lines = [line("o", 1, "Active", ship_date="10/29/2026"),
                 line("o", 2, "Active"), line("o", 3, "Shipped")]
        LR.assign_byod(lines, 1)
        self.assertEqual([LR.is_byod(l) for l in lines], [False, True, False])
        LR.assign_byod(lines, 1)          # already satisfied: no change
        self.assertEqual([LR.is_byod(l) for l in lines], [False, True, False])


class Board(unittest.TestCase):
    def soh(self, *orders):
        return (IX, list(orders), dt.datetime(2026, 11, 6, 6, 30))

    def test_per_line_buckets(self):
        o = order("Nick Smedra", "DSI1", **{"Wireless Status": "Active",
                                          "Wireless Active Date": "10/26/2026",
                                          "Wireless Line Count": "4",
                                          "Port Line Count": "4", "BYOD Line Count": "1"})
        lines = [line("DSI1", 1, "Active", device_type="BYOD"),       # order-dated 10/26
                 line("DSI1", 2, "Active"),                           # live flip seen 11/2 -> 11/1
                 line("DSI1", 3, "Shipped"),                          # open
                 line("DSI1", 4, "Active")]                           # flipped 11/4 -> 11/3 (this week)
        state = {"2145550001": {"first_active": "2026-10-26", "src": "order"},
                 "2145550002": {"first_active": "2026-11-02", "src": "live"},
                 "2145550004": {"first_active": "2026-11-04", "src": "live"}}
        res = LR.compute(self.soh(o), FRI, lines, state, RATES, log=lambda *_: None)
        t = res["tables"]
        last, this = t["last"]["rows"][0], t["this"]["rows"][0]
        self.assertEqual(last["posted"], 188 + 10 + 213 + 10)   # BYOD + Extra, port + Extra
        self.assertEqual(last["pending"], 213)                    # L3 shipped, base only
        self.assertEqual(this["posted"], 213 + 10)
        self.assertEqual(last["canceled"], 0)
        self.assertEqual(res["stats"]["lines"], 4)
        self.assertEqual(t["last"]["label"], "WE 11.1: 10.26 - 11.1")

    def test_paid_then_disconnected_shows_both_and_same_week_only_cancels(self):
        o = order("Jacob Ortega", "DSI2", **{"Wireless Status": "Active/Disconnected",
                                           "Wireless Active Date": "10/31/2026",
                                           "Wireless Line Count": "2", "Port Line Count": "2"})
        lines = [line("DSI2", 1, "Disconnected", tn="3330000001"),   # paid 10/31, died 11/4 (seen 11/5)
                 line("DSI2", 2, "Disconnected", tn="3330000002")]   # active 10/30, died 10/31: same week
        state = {"3330000001": {"first_active": "2026-10-31", "src": "order",
                                "first_dead": "2026-11-05"},
                 "3330000002": {"first_active": "2026-10-31", "src": "live",
                                "first_dead": "2026-11-01"}}
        res = LR.compute(self.soh(o), FRI, lines, state, RATES, log=lambda *_: None)
        last, this = res["tables"]["last"]["rows"][0], res["tables"]["this"]["rows"][0]
        self.assertEqual(last["posted"], 213 + 10)      # L1 only
        self.assertEqual(last["canceled"], 213)         # L2 same-week death: never paid
        self.assertEqual(this["canceled"], 213)         # L1's chargeback week
        self.assertEqual(this["posted"], 0)

    def test_internet_air_and_order_fallback(self):
        air = order("Yahir Lopez", "DSI3", **{"Internet Package": "AT&T Internet Air",
                                            "Internet Status": "Active",
                                            "Internet Install Date": "10/27/2026",
                                            "ABP": "Y"})
        off = order("Eduardo Alvarez", "DSI4", **{"Wireless Status": "Active",
                                                "Wireless Active Date": "10/30/2026",
                                                "Wireless Line Count": "1",
                                                "Port Line Count": "1"})
        open_air = order("Elisa Diaz", "DSI5", **{"Internet Package": "AT&T Internet Air",
                                                "Internet Status": "Open"})
        res = LR.compute(self.soh(air, off, open_air), FRI, [], {}, RATES,
                         log=lambda *_: None)
        rows = {r["rep"]: r for r in res["tables"]["last"]["rows"]}
        self.assertEqual(rows["Yahir Lopez"]["posted"], 123)
        self.assertEqual(rows["Eduardo Alvarez"]["posted"], 213)      # order-level fallback
        self.assertEqual(rows["Elisa Diaz"]["pending"], 93)       # no ABP flag on that order
        self.assertEqual(res["stats"]["orders_off_report"], 1)
        self.assertEqual(res["stats"]["air"], 2)

    def test_feed_line_for_an_order_not_in_the_soh_is_ignored(self):
        o = order("A B", "DSI6", **{"Wireless Status": "Active", "Wireless Active Date": "10/28/2026",
                                  "Wireless Line Count": "1", "Port Line Count": "1"})
        res = LR.compute(self.soh(o), FRI, [line("DSI9", 1, "Active")], {}, RATES,
                         log=lambda *_: None)
        self.assertEqual(res["stats"]["lines"], 0)
        self.assertEqual(res["stats"]["orders_off_report"], 1)


if __name__ == "__main__":
    unittest.main()
