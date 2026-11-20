# -*- coding: utf-8 -*-
"""Per-rep Order Log screenshot (Carlos 2026-11-14; payout columns, totals, the Plan header and the
payout / tier / sales boxes 2026-11-20)."""
import datetime as dt
import unittest
from unittest import mock

from automations.nds_metrics import rep_order_log as ROL
from automations.nds_metrics.run import Cols

RATES = {"wireless": {"port_nonbyod": {"OOF": 213, "INFP": 193}, "port_byod": {"OOF": 188, "INFP": 168},
                      "new_line": 25, "upgrade_voice": 30, "tablet_wearable_nonbyod": 25},
         "internet_air": {"activation": 93, "auto_bill_pay_bonus": 30},
         "rep_tier": {"bands": [[4, 30], [5, 50], [7, 75], [9, 110]], "double_days": []}}
HDR = ["Rep", "sp.Order Date (copy)", "DTR Active Date", "Customer Name", "DTR Status", "spe.Status",
       "Device Description", "Package", "Wireless Installment Plan", "spe.TN", "Customer Zip Simple",
       "spe.Port Carrier", "spe.TN Type", "sp.SPM Number", "spe.Account BAN", "spe.Wireless Type",
       "Product Type (Broken Out)", "spe.Install Date", "IF/OOF", "Auto Bill Pay"]
TODAY = dt.date(2026, 11, 20)                       # Friday; its Mon-Sun week ends Sun 11/22


def _row(**kw):
    base = dict(zip(HDR, ["Esmeralda Gonzalez", "11/3/2026", "11/5/2026", "FELIPE C", "Posted", "Delivered",
                          "iPhone 18 Pro - 256GB - Black", "AT&T Extra 2.0", "Next36 w/ Next Up Anytime",
                          "2145550100", "75060", "T-MOBILE USA", "port", "DSI1", "177145738935", "Phone",
                          "WIRELESS", "", "OOF", ""]))
    base.update(kw); return [base[h] for h in HDR]


def _crew():
    return [_row(),
            _row(**{"spe.TN": "2145550101", "DTR Active Date": "", "DTR Status": "Shipped", "spe.Status": "Shipped",
                    "Device Description": "XT2215-1", "Wireless Installment Plan": "BYOD",
                    "sp.Order Date (copy)": "11/12/2026", "sp.SPM Number": "DSI2"}),
            _row(**{"spe.TN": "2145550102", "DTR Status": "Canceled", "spe.Status": "Canceled", "DTR Active Date": "",
                    "sp.Order Date (copy)": "11/12/2026", "sp.SPM Number": "DSI2"}),
            _row(**{"Product Type (Broken Out)": "AIR", "spe.TN": "", "DTR Status": "Confirmed", "spe.Status": "Active",
                    "sp.Order Date (copy)": "11/10/2026", "sp.SPM Number": "DSI3"}),     # Air: an app, not a log line
            _row(**{"spe.TN": "2145550104", "spe.Wireless Type": "Tablet", "Device Description": "iPad (A16) - 128GB",
                    "sp.Order Date (copy)": "11/10/2026", "sp.SPM Number": "DSI3"}),     # tablet: a line, not an app
            _row(**{"spe.TN": "2145550105", "IF/OOF": "IF", "DTR Status": "Disconnected", "spe.Status": "Disconnected",
                    "sp.Order Date (copy)": "11/17/2026", "DTR Active Date": "11/18/2026", "sp.SPM Number": "DSI4"}),
            _row(**{"spe.TN": "2145550106", "sp.Order Date (copy)": "10/20/2026", "DTR Active Date": "10/22/2026",
                    "sp.SPM Number": "DSI5"}),                                           # sold 5 weeks back
            _row(**{"Rep": "Someone Else", "spe.TN": "2145550109", "sp.SPM Number": "DSI9"})]


class Money(unittest.TestCase):
    def test_columns_in_carlos_order(self):
        # 11/20: Ported From / SPM Number / Wireless Order # / BAN gone; four payout columns right of
        # Est. Revenue; "Package" is headed "Plan" and sits next to Next Up
        self.assertEqual(ROL.COLUMNS, ("Order Date", "Activation Date", "Customer Name", "Status", "Est. Revenue",
                                       "30% Payout", "40% Payout", "45% Payout", "50% Payout",
                                       "Device", "Plan", "Next Up", "Phone Number", "Zip Code"))

    def test_payouts_and_totals(self):
        self.assertEqual(ROL.payouts(213), {"30% Payout": 63.9, "40% Payout": 85.2, "45% Payout": 95.85,
                                            "50% Payout": 106.5})
        self.assertEqual(ROL.payouts(0), {"30% Payout": 0.0, "40% Payout": 0.0, "45% Payout": 0.0, "50% Payout": 0.0})
        lines = [dict({"Est. Revenue": r}, **ROL.payouts(r)) for r in (213, 188, 25)]
        self.assertEqual(ROL.totals(lines), {"Est. Revenue": 426.0, "30% Payout": 127.8, "40% Payout": 170.4,
                                             "45% Payout": 191.7, "50% Payout": 213.0})
        row = ROL.total_row(lines)
        self.assertIn('colspan="4">Total</td>', row)                       # label spans Order Date..Status
        for money in ("$426", "$127.80", "$170.40", "$191.70", "$213.00"):
            self.assertIn(">%s</td>" % money, row)
        self.assertIn('colspan="5"></td>', row)                            # Device..Zip Code


class Lines(unittest.TestCase):
    def setUp(self):
        p = mock.patch("automations.nds_metrics.run.sow_rates", lambda: RATES)
        p.start(); self.addCleanup(p.stop)
        self.cols = Cols(HDR)

    def test_lines_weeks_and_board_prices(self):
        per = ROL.rep_lines(self.cols, _crew(), TODAY)
        self.assertEqual(sorted(per), ["Esmeralda Gonzalez", "Someone Else"])
        esm = per["Esmeralda Gonzalez"]
        self.assertEqual(len(esm), 6)                                       # the Air line is not on the wireless log
        by_tn = dict((ln["Phone Number"], ln) for ln in esm)
        first = by_tn["2145550100"]
        self.assertEqual((first["Status"], first["Est. Revenue"], first["30% Payout"], first["50% Payout"],
                          first["Next Up"], first["Plan"]),
                         ("Posted", 213.0, 63.9, 106.5, "Next Up", "AT&T Extra 2.0"))
        for gone in ("Ported From", "SPM Number", "Wireless Order #", "BAN", "Package"):
            self.assertNotIn(gone, first)
        # priced like the revenue board: BYOD port 188, cancelled 0, tablet 25, in-footprint port 193
        self.assertEqual((by_tn["2145550101"]["Status"], by_tn["2145550101"]["Est. Revenue"],
                          by_tn["2145550101"]["40% Payout"]), ("Shipped", 188.0, 75.2))
        self.assertEqual((by_tn["2145550102"]["Status"], by_tn["2145550102"]["Est. Revenue"],
                          by_tn["2145550102"]["45% Payout"]), ("Cancelled", 0.0, 0.0))
        self.assertEqual(by_tn["2145550104"]["Est. Revenue"], 25.0)
        self.assertEqual(by_tn["2145550105"]["Est. Revenue"], 193.0)
        weeks, pdc = ROL.group_weeks(esm)
        self.assertEqual(sorted(weeks), [(dt.date(2026, 10, 18), dt.date(2026, 10, 24), dt.date(2026, 10, 30)),
                                         (dt.date(2026, 11, 1), dt.date(2026, 11, 7), dt.date(2026, 11, 13))])
        self.assertEqual(sorted(p["Status"] for p in pdc), ["Cancelled", "Disconnected", "Shipped"])

    def test_weekly_sales_are_apps_by_sale_week(self):
        wes, sales = ROL.weekly_sales(self.cols, _crew(), TODAY)
        self.assertEqual(wes, [dt.date(2026, 11, 1), dt.date(2026, 11, 8), dt.date(2026, 11, 15), dt.date(2026, 11, 22)])
        esm = sales["Esmeralda Gonzalez"]
        self.assertEqual(dict(esm[dt.date(2026, 11, 8)]), {"sold": 1, "activated": 1})            # 11/3 port, posted
        # WE 11/15: the BYOD (pending), the cancelled port, the Air (active) -- the tablet is not an app
        self.assertEqual(dict(esm[dt.date(2026, 11, 15)]), {"sold": 3, "pending": 1, "cancelled": 1, "activated": 1})
        self.assertEqual(dict(esm[dt.date(2026, 11, 22)]), {"sold": 1, "activated": 1})           # disconnected after activating
        self.assertNotIn(dt.date(2026, 11, 1), esm)                                               # nothing sold that week
        self.assertEqual(sum(c["sold"] for c in esm.values()), 5)                                 # 10/20 is past the 4 weeks

    def test_tier_standing_is_the_boards_count(self):
        with mock.patch("automations.nds_metrics.double_tier.days", lambda seed, log=print: []):
            week, counts = ROL.tier_standing(self.cols, _crew(), TODAY, log=lambda *_a: None)
        self.assertEqual(week, (dt.date(2026, 11, 15), dt.date(2026, 11, 21)))
        self.assertEqual(counts, {"Esmeralda Gonzalez": (1, 0)})           # one port order this week, its line disconnected

    def test_page(self):
        esm = ROL.rep_lines(self.cols, _crew(), TODAY)["Esmeralda Gonzalez"]
        wes, sales = ROL.weekly_sales(self.cols, _crew(), TODAY)
        tier = ((dt.date(2026, 11, 15), dt.date(2026, 11, 21)), (6, 9))
        page = ROL.html_for("Esmeralda Gonzalez", esm, TODAY, weekly=(wes, sales["Esmeralda Gonzalez"]), tier=tier)
        self.assertIn("Activated Week 11.01 to 11.07", page)               # Carlos 11/20: "activated" next to "week"
        self.assertIn("Paid Friday 11.13", page)
        self.assertEqual(page.count(">Total</td>"), 2)                     # one per activated week, none under pending
        self.assertLess(page.rindex(">Total</td>"), page.index("Pending / Disconnect / Cancel"))
        self.assertIn(">$63.90</td>", page)
        self.assertIn("<th>Plan</th><th>Next Up</th>", page)
        for gone in ("Ported From", "SPM Number", "Wireless Order", ">BAN<", "<th>Package</th>"):
            self.assertNotIn(gone, page)
        # the boxes
        for text in ("Payout Levels", ">Entry Level</td><td class=\"b\">30%</td>", ">Leadership</td><td class=\"b\">40%</td>",
                     "Leadership, 12 apps the week prior</td><td class=\"b\">45%</td>",
                     "Leadership, 16 apps the week prior</td><td class=\"b\">50%</td>"):
            self.assertIn(text, page)
        self.assertIn("Tier Bonus", page)
        for row in ("<td>Tier 1</td><td>4</td><td>$30</td>", '<td class="now">Tier 2</td><td class="now">5\u20136</td>'
                    '<td class="now">$50</td>', "<td>Tier 3</td><td>7\u20138</td><td>$75</td>",
                    "<td>Tier 4</td><td>9+</td><td>$110</td>"):
            self.assertIn(row, page)
        self.assertIn("Week of 11/15 to 11/21: 6 orders, Tier 2.", page)
        self.assertIn("Sales by Week Ending (last 4 weeks)", page)
        self.assertIn('<td class="alt">11/8</td><td class="alt">1</td><td class="alt">1</td><td class="alt">0</td>'
                      '<td class="alt">0</td><td class="alt">100%</td>', page)
        self.assertIn('<td class="">11/15</td><td class="">3</td><td class="">1</td><td class="">1</td>'
                      '<td class="">1</td><td class="">33%</td>', page)
        self.assertIn('<td class="now">11/22*</td><td class="now">1</td><td class="now">1</td>', page)
        self.assertIn('<td class="">11/1</td><td class="">0</td><td class="">0</td><td class="">0</td>'
                      '<td class="">0</td><td class="">-</td>', page)

    def test_tier_box_below_the_first_band_and_without_a_count(self):
        box = ROL.tier_box(((dt.date(2026, 11, 15), dt.date(2026, 11, 21)), (2, 3)))
        self.assertIn("Week of 11/15 to 11/21: 2 orders, 2 more to Tier 1.", box)
        self.assertNotIn('class="now"', box)
        self.assertNotIn("Week of", ROL.tier_box(None))                  # the bands alone when the count is unavailable


if __name__ == "__main__":
    unittest.main()
