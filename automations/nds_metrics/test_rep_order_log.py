# -*- coding: utf-8 -*-
"""Per-rep Order Log screenshot (Carlos 2026-11-14; payout columns + totals 2026-11-20)."""
import datetime as dt
import unittest

from automations.nds_metrics import rep_order_log as ROL
from automations.nds_metrics.run import Cols

RATES = {"wireless": {"port_nonbyod": {"OOF": 213, "INFP": 193}, "port_byod": {"OOF": 188, "INFP": 168},
                      "new_line": 25, "upgrade_voice": 30, "tablet_wearable_nonbyod": 25}}
HDR = ["Rep", "sp.Order Date (copy)", "DTR Active Date", "Customer Name", "DTR Status", "spe.Status",
       "Device Description", "Package", "Wireless Installment Plan", "spe.TN", "Customer Zip Simple",
       "spe.Port Carrier", "spe.TN Type", "sp.SPM Number", "spe.Account BAN", "spe.Wireless Type",
       "Product Type (Broken Out)", "spe.Install Date"]


def _row(**kw):
    base = dict(zip(HDR, ["Esmeralda Gonzalez", "11/3/2026", "11/5/2026", "FELIPE C", "Posted", "Delivered",
                          "iPhone 18 Pro - 256GB - Black", "AT&T Extra 2.0", "Next Up", "2145550100", "75060",
                          "T-MOBILE USA", "port", "DSI1", "177145738935", "Phone", "WIRELESS", ""]))
    base.update(kw); return [base[h] for h in HDR]


class Prices(unittest.TestCase):
    def test_price_rules(self):
        self.assertEqual(ROL.price_line_est(True, False, "Phone", "port", RATES), 213)
        self.assertEqual(ROL.price_line_est(True, True, "Phone", "port", RATES), 188)
        self.assertEqual(ROL.price_line_est(False, False, "Phone", "new", RATES), 25)
        self.assertEqual(ROL.price_line_est(False, False, "Phone", "upgrade", RATES), 30)
        self.assertEqual(ROL.price_line_est(True, False, "Tablet", "port", RATES), 25)

    def test_columns_in_carlos_order(self):
        # 11/20: Ported From / SPM Number / Wireless Order # / BAN gone; four payout columns right of Est. Revenue
        self.assertEqual(ROL.COLUMNS, ("Order Date", "Activation Date", "Customer Name", "Status", "Est. Revenue",
                                       "30% Payout", "40% Payout", "45% Payout", "50% Payout",
                                       "Device", "Package", "Next Up", "Phone Number", "Zip Code"))

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
    def test_lines_and_weeks(self):
        from unittest import mock
        cols = Cols(HDR)
        crew = [_row(),
                _row(**{"spe.TN": "2145550101", "DTR Active Date": "", "DTR Status": "Shipped", "spe.Status": "Shipped",
                        "Device Description": "XT2215-1", "Wireless Installment Plan": "BYOD"}),
                _row(**{"spe.TN": "2145550102", "DTR Status": "Canceled", "spe.Status": "Canceled", "DTR Active Date": ""}),
                _row(**{"Product Type (Broken Out)": "AIR", "spe.TN": ""}),                     # Air: not on the wireless log
                _row(**{"Rep": "Someone Else", "spe.TN": "2145550109"})]

        with mock.patch("automations.nds_metrics.run.sow_rates", lambda: RATES):
            per = ROL.rep_lines(cols, crew, dt.date(2026, 11, 14))
        self.assertEqual(sorted(per), ["Esmeralda Gonzalez", "Someone Else"])
        esm = per["Esmeralda Gonzalez"]
        self.assertEqual(len(esm), 3)
        first = esm[0]
        self.assertEqual((first["Status"], first["Est. Revenue"], first["30% Payout"], first["50% Payout"],
                          first["Next Up"]), ("Posted", 213.0, 63.9, 106.5, "Next Up"))
        for gone in ("Ported From", "SPM Number", "Wireless Order #", "BAN"):
            self.assertNotIn(gone, first)
        self.assertEqual((esm[1]["Status"], esm[1]["Est. Revenue"], esm[1]["40% Payout"]),
                         ("Shipped", 188.0, 75.2))                                          # BYOD port, pending
        self.assertEqual((esm[2]["Status"], esm[2]["Est. Revenue"], esm[2]["45% Payout"]), ("Cancelled", 0.0, 0.0))
        weeks, pdc = ROL.group_weeks(esm)
        self.assertEqual(list(weeks), [(dt.date(2026, 11, 1), dt.date(2026, 11, 7), dt.date(2026, 11, 13))])
        self.assertEqual([p["Status"] for p in pdc], ["Cancelled", "Shipped"])
        page = ROL.html_for("Esmeralda Gonzalez", esm, dt.date(2026, 11, 14))
        self.assertIn("Activated Week 11.01 to 11.07", page)               # Carlos 11/20: "activated" next to "week"
        self.assertIn("Paid Friday 11.13", page)
        self.assertEqual(page.count(">Total</td>"), 1)                     # under the activated week only
        self.assertLess(page.index(">Total</td>"), page.index("Pending / Disconnect / Cancel"))
        self.assertIn(">$63.90</td>", page)
        for gone in ("Ported From", "SPM Number", "Wireless Order", ">BAN<"):
            self.assertNotIn(gone, page)


if __name__ == "__main__":
    unittest.main()
