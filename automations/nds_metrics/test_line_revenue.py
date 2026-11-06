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
    "rep_tier": {"bands": [[4, 30], [5, 50], [7, 75], [9, 110]],
                 "double_days": ["2026-10-31"]},
    "protect_rates": {"periods": [{"from": "2026-09-01", "pa1": 25, "pa4": 75},
                                  {"from": "2026-11-03", "pa1": 15, "pa4": 50}]},
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
        self.assertEqual(LR.activation_date({"first_active": "2026-11-03", "src": "live"}),
                         dt.date(2026, 11, 1))
        # never before the order's own first activation
        self.assertEqual(LR.activation_date({"first_active": "2026-11-03", "src": "live"},
                                            dt.date(2026, 11, 2)),
                         dt.date(2026, 11, 2))
        self.assertEqual(LR.activation_date({"first_active": "2026-10-26", "src": "order"}),
                         dt.date(2026, 10, 26))
        self.assertIsNone(LR.activation_date({}))
        self.assertIsNone(LR.dead_date({"first_dead": "2026-11-05"}, "Active", None))
        self.assertEqual(LR.dead_date({"first_dead": "2026-11-05"}, "Disconnected", None),
                         dt.date(2026, 11, 3))
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
                 "2145550002": {"first_active": "2026-11-03", "src": "live"},
                 "2145550004": {"first_active": "2026-11-05", "src": "live"}}
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
        lines = [line("DSI2", 1, "Disconnected", tn="3330000001"),   # paid 10/31, died 11/3 (seen 11/5)
                 line("DSI2", 2, "Disconnected", tn="3330000002")]   # active 10/30, died 10/31: same week
        state = {"3330000001": {"first_active": "2026-10-31", "src": "order",
                                "first_dead": "2026-11-05"},
                 "3330000002": {"first_active": "2026-11-01", "src": "live",
                                "first_dead": "2026-11-02"}}
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


EXCEL_FEED = b"""<table>
<tr><td></td><td></td><td>Customer Name</td><td>Contact Phone</td><td>Order Number</td><td>Order Date</td><td>Wireless Order Number</td><td>Wireless Account Number</td><td>Lines</td><td>Salesperson</td><td>Dealer Name</td><td>Dealer Code</td><td>Order Status</td></tr>
<tr><td></td><td></td><td>JOHN DOE</td><td>2145550000</td><td>DSI1</td><td>10/28/2026</td><td>99-1</td><td>BAN1</td><td>2</td><td>NICK SMEDRA</td><td>ALPHA</td><td>APCZD</td><td>Active</td></tr>
<tr><td>Line</td><td>Line Type</td><td>Device Type</td><td>Line Number</td><td>Phone</td><td>Plan</td><td>Line Status</td><td>Est. Shipping Range</td><td>Ship Date</td><td>Delieverd Date</td><td>Port Status</td></tr>
<tr><td>1</td><td>Port</td><td>Smartphone</td><td>214-555-0001</td><td>BYOD</td><td>AT&amp;T Extra 2.0</td><td>Active</td><td></td><td></td><td></td><td></td></tr>
<tr><td>2</td><td>Port</td><td>Smartphone</td><td>214-555-0002</td><td>iPhone 18 Pro</td><td>AT&amp;T Premium 2.0</td><td>Shipped</td><td></td><td>10/29/2026</td><td></td><td></td></tr>
<tr><td>1</td><td>Port</td><td>Smartphone</td><td>214-555-0001</td><td>BYOD</td><td>AT&amp;T Extra 2.0</td><td>Active</td><td></td><td></td><td></td><td></td></tr>
<tr><td></td><td></td><td>JANE ROE</td><td>2145550009</td><td>SPM7</td><td>10/23/2026</td><td>99-2</td><td>BAN2</td><td>1</td><td>JORGE H</td><td>ALPHA</td><td>APCZD</td><td>Active</td></tr>
<tr><td>1</td><td>Port</td><td>Smartphone</td><td>214-555-0009</td><td>BYOD</td><td>AT&amp;T Premium 2.0</td><td>Active</td><td></td><td></td><td></td><td></td></tr>
</table>"""


class FeedParse(unittest.TestCase):
    def test_both_orders_and_dedupe(self):
        lines = LR.parse_feed(EXCEL_FEED)
        self.assertEqual([(l["order_id"], l["line_idx"]) for l in lines],
                         [("DSI1", "1"), ("DSI1", "2"), ("SPM7", "1")])   # the repeat dropped, SPM kept
        l1 = lines[0]
        self.assertEqual((l1["tn"], l1["device"], l1["device_type"], l1["plan"], l1["line_status"]),
                         ("2145550001", "BYOD", "Smartphone", "AT&T Extra 2.0", "Active"))
        self.assertEqual(lines[1]["ship_date"], "10/29/2026")
        self.assertEqual(lines[2]["customer"], "JANE ROE")
        self.assertTrue(LR.is_byod(l1))
        self.assertFalse(LR.is_byod(lines[1]))


class RepTier(unittest.TestCase):
    def test_week_and_rate(self):
        self.assertEqual(LR.tier_week(dt.date(2026, 10, 19)), dt.date(2026, 10, 18))   # Monday -> that Sunday
        self.assertEqual(LR.tier_week(dt.date(2026, 10, 25)), dt.date(2026, 10, 25))   # a Sunday starts its week
        self.assertEqual(LR.tier_week(dt.date(2026, 10, 31)), dt.date(2026, 10, 25))
        self.assertEqual([LR.tier_rate(n, RATES) for n in (3, 4, 5, 6, 7, 8, 9, 12)],
                         [0, 30, 50, 50, 75, 75, 110, 110])

    def test_smedra_week_of_10_26_reproduces_the_deposit(self):
        # 6 orders 10/26-10/31 and 10/31 is a double day -> 7 -> $75 on each activated port line
        orders = [order("Nick Smedra", "O%d" % i, order_date=d, **{"Port Line Count": "2"})
                  for i, d in enumerate(("10/26/2026", "10/27/2026", "10/28/2026",
                                         "10/28/2026", "10/30/2026", "10/31/2026"))]
        counts = LR.tier_order_counts(IX, orders, RATES)
        self.assertEqual(counts[("Nick Smedra", dt.date(2026, 10, 25))], 7)
        upg = order("Jacob", "U1", order_date="10/21/2026", **{"Port Line Count": "0", "Upgrade Line Count": "4"})
        self.assertNotIn(("Jacob", dt.date(2026, 10, 18)), LR.tier_order_counts(IX, [upg], RATES))

    def test_tier_rides_the_active_port_line(self):
        orders = [order("Nick Smedra", "DSI%d" % i, order_date="10/2%d/2026" % i,
                        **{"Wireless Status": "Active", "Wireless Active Date": "10/28/2026",
                           "Wireless Line Count": "1", "Port Line Count": "1"})
                  for i in range(1, 5)]                       # 4 orders 10/21-10/24 -> $30
        lines = [line("DSI1", 1, "Active", tn="5550000001", plan="AT&T Value 2.0")]
        state = {"5550000001": {"first_active": "2026-10-28", "src": "order"}}
        res = LR.compute((IX, orders, dt.datetime(2026, 11, 6)), FRI, lines, state, RATES,
                         log=lambda *_: None)
        row = res["tables"]["last"]["rows"][0]
        self.assertEqual(row["posted"], 213 + 30 + 3 * 213)    # the line + its tier, 3 orders at order level
        self.assertEqual(res["stats"]["tier_last"], 30)


class InFootprint(unittest.TestCase):
    def test_if_rates(self):
        self.assertEqual(LR.price_line(line("o", 1, "Active"), RATES, infp=True), (193.0, "port IF"))
        self.assertEqual(LR.price_line(line("o", 1, "Active", device_type="BYOD"), RATES, infp=True),
                         (168.0, "byod port IF"))

    def test_if_numbers_off_the_order_log(self):
        class Cols:
            def __init__(self, hdr):
                self.h = [x.lower() for x in hdr]
            def find(self, *cands):
                for c in cands:
                    if c.lower() in self.h:
                        return self.h.index(c.lower())
                return None
        cols = Cols(["Rep", "IF/OOF", "spe.TN"])
        rows = [["A", "IF", "(972) 900-0215"], ["B", "OOF", "8178847534"], ["C", "", "x"]]
        self.assertEqual(LR.if_numbers(cols, rows, log=lambda *_: None), {"9729000215"})
        self.assertEqual(LR.if_numbers(Cols(["Rep"]), rows, log=lambda *_: None), set())

    def test_compute_prices_the_if_line_and_doubles_the_day(self):
        o = order("Nick", "DSI1", order_date="10/31/2026", **{"Wireless Status": "Active",
                  "Wireless Active Date": "10/31/2026", "Wireless Line Count": "1", "Port Line Count": "1"})
        others = [order("Nick", "DSI%d" % i, order_date="10/27/2026", **{"Port Line Count": "1"}) for i in (2, 3, 4)]
        lines = [line("DSI1", 1, "Active", tn="9729000215", plan="AT&T Value 2.0")]
        state = {"9729000215": {"first_active": "2026-10-31", "src": "order"}}
        res = LR.compute((IX, [o] + others, dt.datetime(2026, 11, 6)), FRI, lines, state, RATES,
                         log=lambda *_: None, if_tns={"9729000215"}, double_days={"2026-10-31"})
        row = res["tables"]["last"]["rows"][0]
        # 3 orders + the doubled 10/31 one = 5 -> $50; the line itself in-footprint $193
        self.assertEqual(row["posted"], 193 + 50)
        self.assertEqual(res["stats"]["if_lines"], 1)


class DoubleTierMail(unittest.TestCase):
    def test_subject_dates(self):
        from automations.nds_metrics import double_tier as DT
        sent = dt.date(2026, 10, 30)
        self.assertEqual(DT.parse_subject("Double Tier Bonus  - 10/31", sent), dt.date(2026, 10, 31))
        self.assertEqual(DT.parse_subject("Re: Double Tier Bonus - 10/12", sent), dt.date(2026, 10, 12))
        self.assertEqual(DT.parse_subject("Double Tiers Bonus: 1/2", dt.date(2026, 12, 31)), dt.date(2027, 1, 2))
        self.assertIsNone(DT.parse_subject("Checking Historical Rep Tier Status (NDS)", sent))


class Protect(unittest.TestCase):
    def test_rate_by_plan_and_sale_date(self):
        self.assertEqual(LR.protect_rate("AT&T Protect Advantage for 1", dt.date(2026, 10, 23), RATES), 25)
        self.assertEqual(LR.protect_rate("Protect Advantage for 4 Devices", dt.date(2026, 10, 23), RATES), 75)
        self.assertEqual(LR.protect_rate("Protect Advantage for 1", dt.date(2026, 11, 3), RATES), 15)
        self.assertEqual(LR.protect_rate("PA4", dt.date(2026, 11, 5), RATES), 50)
        self.assertEqual(LR.protect_rate("", dt.date(2026, 11, 5), RATES), 15)

    def test_plan_rides_the_first_activated_line(self):
        o = order("Yahir", "DSI1", order_date="10/23/2026", **{"Wireless Status": "Active",
                  "Wireless Active Date": "11/01/2026", "Wireless Line Count": "1", "Port Line Count": "1"})
        lines = [line("DSI1", 1, "Active", tn="3363839250", plan="AT&T Value 2.0")]
        state = {"3363839250": {"first_active": "2026-11-03", "src": "live"}}      # -> 11/1
        res = LR.compute((IX, [o], dt.datetime(2026, 11, 6)), FRI, lines, state, RATES,
                         log=lambda *_: None,
                         protect={"DSI1": {"sold": "1", "plan": "AT&T Protect Advantage for 1", "status": "Active"}})
        row = res["tables"]["last"]["rows"][0]
        self.assertEqual(row["posted"], 213 + 25)
        self.assertEqual(res["stats"]["protect_plans"], 1)
        self.assertEqual(res["stats"]["protect_last"], 25)
