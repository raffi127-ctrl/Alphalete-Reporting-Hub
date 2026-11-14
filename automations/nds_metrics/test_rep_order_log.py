# -*- coding: utf-8 -*-
"""Per-rep Order Log screenshot (Carlos 2026-11-14)."""
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
        self.assertEqual(ROL.COLUMNS, ("Order Date", "Activation Date", "Customer Name", "Status", "Est. Revenue",
                                       "Device", "Package", "Next Up", "Phone Number", "Zip Code", "Ported From",
                                       "SPM Number", "Wireless Order #", "BAN"))


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

        class _Idx:
            def value(self, header, phone="", dsi=""):
                return "99-1" if phone == "2145550100" else ""
        with mock.patch("automations.nds_metrics.run.sow_rates", lambda: RATES):
            per = ROL.rep_lines(cols, crew, dt.date(2026, 11, 14), index=_Idx())
        self.assertEqual(sorted(per), ["Esmeralda Gonzalez", "Someone Else"])
        esm = per["Esmeralda Gonzalez"]
        self.assertEqual(len(esm), 3)
        first = esm[0]
        self.assertEqual((first["Status"], first["Est. Revenue"], first["Ported From"], first["Wireless Order #"],
                          first["BAN"], first["Next Up"]),
                         ("Posted", 213.0, "T-MOBILE USA", "99-1", "177145738935", "Next Up"))
        self.assertEqual((esm[1]["Status"], esm[1]["Est. Revenue"]), ("Shipped", 188.0))   # BYOD port, pending
        self.assertEqual(esm[2]["Status"], "Cancelled")
        weeks, pdc = ROL.group_weeks(esm)
        self.assertEqual(list(weeks), [(dt.date(2026, 11, 1), dt.date(2026, 11, 7), dt.date(2026, 11, 13))])
        self.assertEqual([p["Status"] for p in pdc], ["Cancelled", "Shipped"])


if __name__ == "__main__":
    unittest.main()
