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
         "addons": {"next_up": 15, "unlimited_premium": 15, "unlimited_extra": 10, "oof_bundle_with_internet_air": 25},
         "rep_tier": {"bands": [[4, 30], [5, 50], [7, 75], [9, 110]], "double_days": []}}
HDR = ["Rep", "sp.Order Date (copy)", "DTR Active Date", "Customer Name", "DTR Status", "spe.Status",
       "Device Description", "Package", "Wireless Installment Plan", "spe.TN", "Customer Zip Simple",
       "spe.Port Carrier", "spe.TN Type", "sp.SPM Number", "spe.Account BAN", "spe.Wireless Type",
       "Product Type (Broken Out)", "spe.Install Date", "IF/OOF", "Auto Bill Pay", "Rep Tier Bonus Status",
       "Status Date", "cl.DD Date"]
TODAY = dt.date(2026, 11, 20)                       # Friday; its Mon-Sun week ends Sun 11/22


def _row(**kw):
    base = dict(zip(HDR, ["Esmeralda Gonzalez", "11/3/2026", "11/5/2026", "FELIPE C", "Posted", "Delivered",
                          "iPhone 18 Pro - 256GB - Black", "AT&T Extra 2.0", "Next36 w/o Next Up",
                          "2145550100", "75060", "T-MOBILE USA", "port", "DSI1", "177145738935", "Phone",
                          "WIRELESS", "", "OOF", "", "0", "", ""]))
    base.update(kw); return [base[h] for h in HDR]


def _crew():
    return [_row(),
            _row(**{"spe.TN": "2145550101", "DTR Active Date": "", "DTR Status": "Shipped", "spe.Status": "Shipped",
                    "Device Description": "XT2215-1", "Wireless Installment Plan": "BYOD",
                    "sp.Order Date (copy)": "11/12/2026", "sp.SPM Number": "DSI2"}),
            _row(**{"spe.TN": "2145550102", "DTR Status": "Canceled", "spe.Status": "Canceled", "DTR Active Date": "",
                    "sp.Order Date (copy)": "11/12/2026", "sp.SPM Number": "DSI2"}),
            _row(**{"Product Type (Broken Out)": "AIR", "spe.TN": "", "DTR Status": "Confirmed", "spe.Status": "Active",
                    "sp.Order Date (copy)": "11/10/2026", "sp.SPM Number": "DSI3",
                    "Package": "AT&T Internet Air"}),                                    # Air: an app, not a log line
            _row(**{"spe.TN": "2145550104", "spe.Wireless Type": "Tablet", "Device Description": "iPad (A16) - 128GB",
                    "sp.Order Date (copy)": "11/10/2026", "sp.SPM Number": "DSI3",
                    "Package": "AT&T DataConnect 100GB"}),                               # tablet: a line, not an app
            _row(**{"spe.TN": "2145550105", "IF/OOF": "IF", "DTR Status": "Disconnected", "spe.Status": "Disconnected",
                    "sp.Order Date (copy)": "11/17/2026", "DTR Active Date": "11/18/2026", "sp.SPM Number": "DSI4",
                    "Package": "AT&T Premium 2.0", "Status Date": "11/19/2026"}),       # same deposit week: unpaid
            _row(**{"spe.TN": "2145550106", "sp.Order Date (copy)": "10/20/2026", "DTR Active Date": "10/22/2026",
                    "sp.SPM Number": "DSI5"}),                                           # sold 5 weeks back
            _row(**{"Rep": "Someone Else", "spe.TN": "2145550109", "sp.SPM Number": "DSI9"})]


class Money(unittest.TestCase):
    def test_columns_in_carlos_order(self):
        # 11/20: Ported From / SPM Number / Wireless Order # / BAN gone; "Package" is headed "Plan" and sits
        # next to Next Up; Est. Revenue + the four payout columns close the table, far right
        self.assertEqual(ROL.COLUMNS, ("Order Date", "Activation Date", "Customer Name", "Status",
                                       "Device \u00b7 Phone \u00b7 Zip", "Plan", "Tier", "Est. Revenue",
                                       "30% Payout", "40% Payout", "45% Payout", "50% Payout"))

    def test_payouts_and_totals(self):
        self.assertEqual(ROL.payouts(213), {"30% Payout": 63.9, "40% Payout": 85.2, "45% Payout": 95.85,
                                            "50% Payout": 106.5})
        self.assertEqual(ROL.payouts(0), {"30% Payout": 0.0, "40% Payout": 0.0, "45% Payout": 0.0, "50% Payout": 0.0})
        lines = [dict({"Est. Revenue": r}, **ROL.payouts(r)) for r in (213, 188, 25)]
        self.assertEqual(ROL.totals(lines), {"Est. Revenue": 426.0, "30% Payout": 127.8, "40% Payout": 170.4,
                                             "45% Payout": 191.7, "50% Payout": 213.0})
        row = ROL.total_row(lines)
        self.assertIn('colspan="7">Total</td>', row)                       # label spans Order Date..Tier
        for money in ("$426", "$127.80", "$170.40", "$191.70", "$213.00"):
            self.assertIn(">%s</td>" % money, row)
        self.assertTrue(row.endswith('<td class="tot">$213.00</td></tr>'))  # the 50% total is the last cell


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
        # Est. Revenue = the board's line price + the plan's add-on (Carlos 11/20): port 213 + Extra 10
        self.assertEqual((first["Status"], first["Est. Revenue"], first["30% Payout"], first["50% Payout"],
                          first["Next Up"], first["Plan"]),
                         ("Posted", 223.0, 66.9, 111.5, "No Next Up", "Extra"))
        for gone in ("Ported From", "SPM Number", "Wireless Order #", "BAN", "Package"):
            self.assertNotIn(gone, first)
        self.assertEqual(first["Plan Name"], "AT&T Extra 2.0")
        # priced like the revenue board + the plan: BYOD port 188 + Extra 10, cancelled 0, tablet 25 (a data
        # plan adds nothing), in-footprint port 193 + Premium 15
        self.assertEqual((by_tn["2145550101"]["Status"], by_tn["2145550101"]["Est. Revenue"],
                          by_tn["2145550101"]["40% Payout"]), ("Shipped", 198.0, 79.2))
        self.assertEqual((by_tn["2145550102"]["Status"], by_tn["2145550102"]["Est. Revenue"],
                          by_tn["2145550102"]["45% Payout"]), ("Cancelled", 0.0, 0.0))
        self.assertEqual(by_tn["2145550104"]["Est. Revenue"], 25.0)
        # activated 11/18 and disconnected 11/19, the same Mon-Sun deposit week: never paid (SOW)
        self.assertEqual((by_tn["2145550105"]["Status"], by_tn["2145550105"]["Est. Revenue"]), ("Disconnected", 0.0))
        value = _row(**{"Package": "AT&T Value 2.0"})
        self.assertEqual(ROL.rep_lines(self.cols, [value], TODAY)["Esmeralda Gonzalez"][0]["Est. Revenue"], 213.0)
        weeks, pdc = ROL.group_weeks(esm)
        # the deposit's Mon-Sun weeks, paid the Friday after (Carlos 11/20: the Sunday discrepancy)
        self.assertEqual(sorted(weeks), [(dt.date(2026, 10, 19), dt.date(2026, 10, 25), dt.date(2026, 10, 30)),
                                         (dt.date(2026, 11, 2), dt.date(2026, 11, 8), dt.date(2026, 11, 13))])
        self.assertEqual(sorted(p["Status"] for p in pdc), ["Cancelled", "Disconnected", "Shipped"])

    def test_a_blank_plan_and_device_come_off_the_order_log_tab(self):
        """Carlos 11/20: "you don't have the plan filled out for everyone" -- a fresh order has no Package /
        Device on the export yet; the tab (the SaraPlus feed) has both, and the price follows them."""
        hdr = ["Week Ending", "Rep", "Phone #", "DSI #", "Plan", "Device"]
        tab = ROL.TabPlans(hdr, [["11/22/2026", "Esmeralda Gonzalez", "830-765-4213", "DSI9", "AT&T Premium 2.0", "BYOD"],
                                 ["11/22/2026", "Esmeralda Gonzalez", "315-690-1264", "DSI9", "AT&T Premium 2.0", "iPhone 18 - 256GB - Black"],
                                 ["11/22/2026", "Esmeralda Gonzalez", "443-813-2865", "DSI8", "AT&T Extra 2.0", "BYOD"],
                                 ["11/22/2026", "Esmeralda Gonzalez", "945-358-3618", "DSI8", "AT&T Premium 2.0", "BYOD"]])
        self.assertEqual(tab.get("Plan", "(830) 765-4213", ""), "AT&T Premium 2.0")       # by the number, any spelling
        self.assertEqual(tab.get("Plan", "", "dsi9"), "AT&T Premium 2.0")                 # no number: the order agrees
        self.assertEqual(tab.get("Plan", "2140000000", "DSI8"), "")                       # the order's lines differ: no guess
        self.assertEqual((tab.filled, tab.missed), (2, 1))
        new = _row(**{"spe.TN": "8307654213", "sp.SPM Number": "DSI9", "Package": "", "Device Description": "",
                      "Wireless Installment Plan": "", "sp.Order Date (copy)": "11/19/2026", "DTR Active Date": "",
                      "DTR Status": "", "spe.Status": ""})
        bare = ROL.rep_lines(self.cols, [new], TODAY)["Esmeralda Gonzalez"][0]
        self.assertEqual((bare["Plan"], bare["Device"], bare["Est. Revenue"]), ("", "", 213.0))
        line = ROL.rep_lines(self.cols, [new], TODAY, tab=tab)["Esmeralda Gonzalez"][0]
        self.assertEqual((line["Plan"], line["Device"]), ("Premium", "BYOD"))
        self.assertEqual(line["Est. Revenue"], 203.0)                                     # BYOD port 188 + Premium 15
        _w, sales = ROL.weekly_sales(self.cols, [new], TODAY, tab=tab)
        self.assertEqual(sales["Esmeralda Gonzalez"][dt.date(2026, 11, 22)]["revenue"], 203.0)

    def test_weekly_sales_are_apps_by_sale_week(self):
        wes, sales = ROL.weekly_sales(self.cols, _crew(), TODAY)
        self.assertEqual(wes, [dt.date(2026, 10, 25), dt.date(2026, 11, 1), dt.date(2026, 11, 8), dt.date(2026, 11, 15),
                               dt.date(2026, 11, 22)])                                            # 5 weeks (Carlos 11/20)
        esm = sales["Esmeralda Gonzalez"]
        self.assertEqual(dict(esm[dt.date(2026, 10, 25)]), {"sold": 1, "activated": 1, "revenue": 223.0})   # the 10/20 port, Extra
        self.assertEqual(dict(esm[dt.date(2026, 11, 8)]), {"sold": 1, "activated": 1, "revenue": 223.0})    # 11/3 port, posted
        # WE 11/15: the BYOD (pending, 188 + 10), the cancelled port (0), the Air (active, 93) are the apps;
        # the tablet (25) is not an app but its money is in the week's revenue
        self.assertEqual(dict(esm[dt.date(2026, 11, 15)]),
                         {"sold": 3, "pending": 1, "cancelled": 1, "activated": 1, "revenue": 316.0})
        self.assertEqual(dict(esm[dt.date(2026, 11, 22)]), {"sold": 1, "activated": 1, "revenue": 0.0})     # activated, then disconnected the same week: unpaid
        self.assertNotIn(dt.date(2026, 11, 1), esm)                                               # nothing sold that week
        wes4, _s = ROL.weekly_sales(self.cols, _crew(), TODAY, weeks=4)
        self.assertEqual(wes4[0], dt.date(2026, 11, 1))

    def test_a_line_sara_shows_active_goes_in_saras_week_until_tableau_posts(self):
        """Carlos 11/20: "Put them wherever Sara shows that they activated under. Once the posted date comes
        up, you move them if needed"."""
        shipped = dict(**{"DTR Status": "Shipped", "spe.Status": "Shipped", "DTR Active Date": "",
                          "sp.Order Date (copy)": "11/10/2026"})
        rows = [_row(**dict(shipped, **{"spe.TN": "2145550401", "sp.SPM Number": "S1"})),      # Sara: active 11/16
                _row(**dict(shipped, **{"spe.TN": "2145550402", "sp.SPM Number": "S2"})),      # Sara: not active
                _row(**{"spe.TN": "2145550403", "sp.SPM Number": "S3", "DTR Active Date": "11/12/2026"}),  # posted
                _row(**dict(shipped, **{"spe.TN": "2145550404", "sp.SPM Number": "S4",
                                        "DTR Status": "Canceled", "spe.Status": "Canceled"}))]  # dead stays dead
        sara = {ROL.line_key("S1", "2145550401"): dt.date(2026, 11, 16),
                ROL.line_key("S3", "2145550403"): dt.date(2026, 11, 13),                     # Tableau's date wins
                ROL.line_key("S4", "2145550404"): dt.date(2026, 11, 16),
                ROL.line_key("", "2145550401"): dt.date(2026, 11, 16)}
        lines = dict((ln["Phone Number"], ln) for ln in ROL.rep_lines(self.cols, rows, TODAY, sara=sara)["Esmeralda Gonzalez"])
        self.assertEqual((lines["2145550401"]["Status"], lines["2145550401"]["Activation Date"]),
                         ("Active", dt.date(2026, 11, 16)))
        self.assertEqual((lines["2145550402"]["Status"], lines["2145550402"]["Activation Date"]), ("Shipped", None))
        self.assertEqual((lines["2145550403"]["Status"], lines["2145550403"]["Activation Date"]),
                         ("Posted", dt.date(2026, 11, 12)))
        self.assertEqual(lines["2145550404"]["Status"], "Cancelled")
        weeks, pdc = ROL.group_weeks(list(lines.values()))
        self.assertEqual(sorted(k[0] for k in weeks), [dt.date(2026, 11, 9), dt.date(2026, 11, 16)])
        self.assertEqual([ln["Phone Number"] for ln in weeks[(dt.date(2026, 11, 16), dt.date(2026, 11, 22),
                                                              dt.date(2026, 11, 27))]], ["2145550401"])
        self.assertEqual(sorted(ln["Phone Number"] for ln in pdc), ["2145550402", "2145550404"])
        # 11/20 cross-check: a number re-placed on a NEW order activates there only, never the old order's line
        moved = _row(**dict(shipped, **{"spe.TN": "2145550401", "sp.SPM Number": "OLD1"}))
        both = ROL.mark_replaced(self.cols, [rows[0], moved], sara)
        old_line = ROL.rep_lines(self.cols, [moved], TODAY, sara=both)["Esmeralda Gonzalez"][0]
        self.assertEqual((old_line["Status"], old_line["Activation Date"]), ("Shipped", None))
        # ... but a number on ONE export order is placed by number (the export's id can be an SPM id)
        alone = ROL.mark_replaced(self.cols, [moved], sara)
        self.assertEqual(ROL.rep_lines(self.cols, [moved], TODAY, sara=alone)["Esmeralda Gonzalez"][0]["Status"], "Active")
        # no SaraPlus read: as before
        bare = dict((ln["Phone Number"], ln) for ln in ROL.rep_lines(self.cols, rows, TODAY)["Esmeralda Gonzalez"])
        self.assertEqual(bare["2145550401"]["Status"], "Shipped")
        # the weekly table counts it activated
        _w, sales = ROL.weekly_sales(self.cols, rows[:2], TODAY, sara=sara)
        self.assertEqual(dict(sales["Esmeralda Gonzalez"][dt.date(2026, 11, 15)])["activated"], 1)
        # and the comparison counts the one line both have dated
        self.assertEqual(ROL.compare_sara_tableau(self.cols, rows, sara, log=lambda *_a: None), {"both": 1, "moved": 0})

    def test_deposit_itemising_order_and_disconnects(self):
        """Carlos 11/20: upgrades show '(Upgrade)' and pay $30 flat; plan add-on + Next Up only on port
        lines; lines by order date with disconnects then cancels at the bottom; a disconnect that was
        paid stays green as 'Activated (Disconnected)' in its activated week."""
        rows = [_row(**{"spe.TN": "2145550501", "sp.Order Date (copy)": "11/4/2026", "DTR Active Date": "11/4/2026",
                        "spe.TN Type": "upgrade", "spe.Port Carrier": "", "sp.SPM Number": "U1"}),
                _row(**{"spe.TN": "2145550502", "sp.Order Date (copy)": "11/2/2026", "DTR Active Date": "11/5/2026",
                        "Wireless Installment Plan": "Next36 w/ Next Up Anytime", "Package": "AT&T Premium 2.0",
                        "sp.SPM Number": "P1"}),
                _row(**{"spe.TN": "2145550503", "sp.Order Date (copy)": "11/1/2026", "DTR Active Date": "11/3/2026",
                        "DTR Status": "Disconnected", "spe.Status": "Disconnected", "Status Date": "11/12/2026",
                        "sp.SPM Number": "D1"}),                                   # disconnected a week later: paid
                _row(**{"spe.TN": "2145550504", "sp.Order Date (copy)": "11/3/2026", "DTR Active Date": "11/6/2026",
                        "sp.SPM Number": "P2"}),
                _row(**{"spe.TN": "2145550505", "sp.Order Date (copy)": "11/1/2026", "DTR Active Date": "",
                        "DTR Status": "Canceled", "spe.Status": "Canceled", "sp.SPM Number": "C1"}),
                _row(**{"spe.TN": "2145550506", "sp.Order Date (copy)": "11/2/2026", "DTR Active Date": "",
                        "DTR Status": "Disconnected", "spe.Status": "Disconnected", "sp.SPM Number": "D2"}),  # never active
                _row(**{"spe.TN": "2145550507", "sp.Order Date (copy)": "11/5/2026", "DTR Active Date": "",
                        "DTR Status": "Shipped", "spe.Status": "Shipped", "sp.SPM Number": "S1"})]
        esm = ROL.rep_lines(self.cols, rows, TODAY)["Esmeralda Gonzalez"]
        by = dict((ln["Phone Number"], ln) for ln in esm)
        self.assertEqual((by["2145550501"]["Device"], by["2145550501"]["Est. Revenue"]),
                         ("iPhone 18 Pro - 256GB - Black (Upgrade)", 30.0))           # no plan add-on on an upgrade
        self.assertEqual(by["2145550502"]["Est. Revenue"], 213.0 + 15 + 15)          # port + Premium + Next Up
        self.assertEqual(by["2145550502"]["Plan"], "Premium + Next Up")             # Carlos 11/20: one column
        self.assertEqual(by["2145550504"]["Plan"], "Extra")                         # no Next Up: just the plan
        self.assertEqual((by["2145550503"]["Status"], by["2145550503"]["Est. Revenue"]), (ROL.ACT_DISC, 223.0))
        self.assertEqual((by["2145550506"]["Status"], by["2145550506"]["Est. Revenue"]), ("Disconnected", 0.0))
        weeks, pdc = ROL.group_weeks(esm)
        wk = weeks[(dt.date(2026, 11, 2), dt.date(2026, 11, 8), dt.date(2026, 11, 13))]
        # by ORDER date, the paid disconnect last in its week
        self.assertEqual([ln["Phone Number"] for ln in wk], ["2145550502", "2145550504", "2145550501", "2145550503"])
        self.assertEqual([ln["Phone Number"] for ln in pdc], ["2145550507", "2145550506", "2145550505"])  # pending, disc, cancel
        page = ROL.html_for("Esmeralda Gonzalez", esm, TODAY)
        self.assertIn('<td style="background:#57BB8A;color:#000000">Activated (Disconnected)</td>', page)   # green

    def test_sunday_activations_follow_the_deposit_week(self):
        """Carlos 11/20: Subba Rao and Georgeatte (activated Sun 11/1) were paid on CS 11.1, not 11.8; a line
        already paid sits under its cl.DD Date (Sundararaghandran, Sun 11/8, paid on CS 11.15)."""
        self.assertEqual(ROL.pay_week(dt.date(2026, 11, 1)), (dt.date(2026, 10, 26), dt.date(2026, 11, 1), dt.date(2026, 11, 6)))
        self.assertEqual(ROL.pay_week(dt.date(2026, 11, 7)), (dt.date(2026, 11, 2), dt.date(2026, 11, 8), dt.date(2026, 11, 13)))
        rows = [_row(**{"spe.TN": "2145550701", "DTR Active Date": "11/1/2026", "sp.Order Date (copy)": "10/29/2026"}),
                _row(**{"spe.TN": "2145550702", "DTR Active Date": "11/7/2026", "sp.Order Date (copy)": "11/6/2026"}),
                _row(**{"spe.TN": "2145550703", "DTR Active Date": "11/8/2026", "sp.Order Date (copy)": "10/30/2026",
                        "cl.DD Date": "11/15/2026"})]
        esm = ROL.rep_lines(self.cols, rows, TODAY)["Esmeralda Gonzalez"]
        weeks, _pdc = ROL.group_weeks(esm)
        where = dict((ln["Phone Number"], k[2]) for k, lns in weeks.items() for ln in lns)
        self.assertEqual(where, {"2145550701": dt.date(2026, 11, 6),     # Sunday 11/1 -> week ending 11/1, paid 11/6
                                 "2145550702": dt.date(2026, 11, 13),    # Saturday 11/7 -> week ending 11/8, paid 11/13
                                 "2145550703": dt.date(2026, 11, 20)})   # paid on the 11/15 deposit -> 11/20

    def test_plan_and_device_cells(self):
        self.assertEqual([ROL.short_plan(p) for p in ("AT&T Extra 2.0", "AT&T Premium 2.0", "AT&T 55+",
                                                      "AT&T DataConnect 100GB", "")],
                         ["Extra", "Premium", "55+", "DataConnect 100GB", ""])
        self.assertEqual(ROL.plan_cell("AT&T Value 2.0", "Next Up"), "Value + Next Up")
        self.assertEqual(ROL.plan_cell("AT&T Value 2.0", "BYOD"), "Value")
        self.assertEqual(ROL.plan_cell("", "Next Up"), "Next Up")
        self.assertEqual(ROL.fmt_phone("(972) 900-1732"), "972-900-1732")
        byod = _row(**{"spe.TN": "2145550601", "Device Description": "iPhone 13 A2482", "Wireless Installment Plan": "BYOD"})
        line = ROL.rep_lines(self.cols, [byod], TODAY)["Esmeralda Gonzalez"][0]
        self.assertEqual(line["Device"], "iPhone 13 A2482 (BYOD)")
        byo = _row(**{"spe.TN": "2145550602", "Device Description": "SM-G991U BYO", "Wireless Installment Plan": "BYOD"})
        self.assertEqual(ROL.rep_lines(self.cols, [byo], TODAY)["Esmeralda Gonzalez"][0]["Device"], "SM-G991U BYO")

    def test_tableau_posted_date_only(self):
        """Carlos 11/20 night: "we could just use the posted date on tableau" -- a line SaraPlus shows Active
        that Tableau has not posted is Pending ("Active (not posted)"); the posted date places a line too."""
        rows = [_row(**{"spe.TN": "2145550801", "DTR Status": "Shipped", "spe.Status": "Active", "DTR Active Date": "",
                        "sp.Order Date (copy)": "11/16/2026"}),
                _row(**{"spe.TN": "2145550802", "DTR Status": "Posted", "spe.Status": "Active", "DTR Active Date": "",
                        "spe.dtr Posted Date": "11/17/2026", "sp.Order Date (copy)": "11/16/2026"})]
        cols = Cols(HDR + ["spe.dtr Posted Date"])
        rows = [r + ["" if i == 0 else "11/17/2026"] for i, r in enumerate(rows)]
        esm = dict((ln["Phone Number"], ln) for ln in ROL.rep_lines(cols, rows, TODAY)["Esmeralda Gonzalez"])
        self.assertEqual((esm["2145550801"]["Status"], esm["2145550801"]["Activation Date"]), (ROL.NOT_POSTED, None))
        self.assertEqual((esm["2145550802"]["Status"], esm["2145550802"]["Activation Date"]),
                         ("Posted", dt.date(2026, 11, 17)))
        weeks, pdc = ROL.group_weeks(list(esm.values()))
        self.assertEqual([ln["Phone Number"] for ln in pdc], ["2145550801"])
        self.assertEqual(list(weeks), [(dt.date(2026, 11, 16), dt.date(2026, 11, 22), dt.date(2026, 11, 27))])
        _w, sales = ROL.weekly_sales(cols, rows, TODAY)
        c = sales["Esmeralda Gonzalez"][dt.date(2026, 11, 22)]
        self.assertEqual((c["activated"], c["pending"]), (1, 1))

    def test_tier_bonus_per_port_line(self):
        """Carlos 11/20: "are you accounting for the tier in the revenue as well?" -- a port line earns its
        LOGIN's tier for the Sun-Sat week of its order; a Posted line's own status wins."""
        mk = lambda n, **kw: _row(**dict({"Rep": "Aaron De La Torre", "sp.Order Date (copy)": "11/12/2026",
                                          "DTR Status": "Shipped", "spe.Status": "Shipped", "DTR Active Date": "",
                                          "spe.TN": "21455503%02d" % n, "sp.SPM Number": "A%d" % n,
                                          "Rep Tier Bonus Status": ""}, **kw))
        rows = [mk(n) for n in range(4)]                                   # 4 orders in 11/8 - 11/14: Tier 1, $30
        rows += [mk(9, **{"Rep": "Esmeralda Gonzalez"}),                   # 1 order: nothing
                 mk(8, **{"spe.TN Type": "upgrade", "spe.Port Carrier": ""}),      # an upgrade earns none
                 mk(7, **{"spe.Wireless Type": "Tablet", "spe.TN Type": "new", "spe.Port Carrier": ""}),  # a tablet earns none
                 mk(6, **{"DTR Status": "Posted", "Rep Tier Bonus Status": "50", "sp.SPM Number": "A0"})]  # posted: its own
        with mock.patch("automations.nds_metrics.double_tier.days", lambda seed, log=print: set()):
            tiers = ROL.line_tier_rates(self.cols, rows, log=lambda *_a: None)
        self.assertEqual(tiers[ROL.line_key("A1", "2145550301")], 30.0)
        self.assertEqual(tiers[ROL.line_key("A9", "2145550309")], 0.0)
        self.assertNotIn(ROL.line_key("A8", "2145550308"), tiers)
        self.assertNotIn(ROL.line_key("A7", "2145550307"), tiers)
        self.assertEqual(tiers[ROL.line_key("A0", "2145550306")], 50.0)
        # it lands in Est. Revenue (and the payouts), not on a cancelled line
        per = ROL.rep_lines(self.cols, rows, TODAY, tier_by_line=tiers)
        line = [ln for ln in per["Aaron De La Torre"] if ln["Phone Number"] == "2145550301"][0]
        self.assertEqual((line["Est. Revenue"], line["30% Payout"]), (253.0, 75.9))    # 213 + Extra 10 + tier 30
        self.assertEqual(line["Tier"], "Tier 1")                                      # Carlos 11/20: the Tier column
        posted = [ln for ln in per["Aaron De La Torre"] if ln["Phone Number"] == "2145550306"][0]
        self.assertEqual(posted["Tier"], "Tier 2")
        upgrade = [ln for ln in per["Aaron De La Torre"] if ln["Phone Number"] == "2145550308"][0]
        self.assertEqual(upgrade["Tier"], "")                                         # no tier on an upgrade
        self.assertEqual([ROL.tier_name_for(v) for v in (0, 30, 50, 75, 110, 40)],
                         ["", "Tier 1", "Tier 2", "Tier 3", "Tier 4", "$40"])
        dead = ROL.rep_lines(self.cols, [mk(1, **{"DTR Status": "Canceled", "spe.Status": "Canceled"})], TODAY,
                             tier_by_line=tiers)["Aaron De La Torre"][0]
        self.assertEqual((dead["Est. Revenue"], dead["Tier"]), (0.0, ""))
        _w, sales = ROL.weekly_sales(self.cols, rows[:4], TODAY, tier_by_line=tiers)
        self.assertEqual(sales["Aaron De La Torre"][dt.date(2026, 11, 15)]["revenue"], 4 * 253.0)

    def test_tier_weeks_are_the_boards_count_with_one_inbox_read(self):
        wes, _s = ROL.weekly_sales(self.cols, _crew(), TODAY)
        reads = []
        with mock.patch("automations.nds_metrics.double_tier.days",
                        lambda seed, log=print: reads.append(1) or {"2026-11-12"}):
            tiers = ROL.tier_weeks(self.cols, _crew(), wes, log=lambda *_a: None)
        self.assertEqual(len(reads), 1)                                    # five weeks, one read of the double-tier days
        self.assertEqual(sorted(tiers), wes)
        # WE 11/22 -> tier week Sun 11/15 - Sat 11/21: one port order, its line disconnected
        self.assertEqual(tiers[dt.date(2026, 11, 22)], {"Esmeralda Gonzalez": (1, 0)})
        # WE 11/15 -> 11/8 - 11/14: DSI3 (the tablet's port) + DSI2 sold on the 11/12 double-tier day = 3
        self.assertEqual(tiers[dt.date(2026, 11, 15)]["Esmeralda Gonzalez"][0], 3)
        self.assertEqual(tiers[dt.date(2026, 11, 8)]["Esmeralda Gonzalez"][0], 1)      # 11/3 (Someone Else has one too)
        self.assertEqual(tiers[dt.date(2026, 11, 1)], {})
        self.assertEqual(ROL.tier_week_of(dt.date(2026, 11, 22)), (dt.date(2026, 11, 15), dt.date(2026, 11, 21)))

    def test_tier_label(self):
        bands = [(4, 30.0), (5, 50.0), (7, 75.0), (9, 110.0)]
        self.assertEqual([ROL.tier_label(n, bands) for n in (0, 3, 4, 5, 6, 7, 8, 9, 14)],
                         ["-", "-", "Tier 1", "Tier 2", "Tier 2", "Tier 3", "Tier 3", "Tier 4", "Tier 4"])
        # what Smart Circle has posted wins when it is the higher one (a count of 3 paid at $30 = Tier 1)
        self.assertEqual(ROL.tier_label(3, bands, paid_rate=30.0), "Tier 1")
        self.assertEqual(ROL.tier_label(5, bands, paid_rate=30.0), "Tier 2")
        self.assertEqual(ROL.tier_label(0, bands, paid_rate=75.0), "Tier 3")
        self.assertEqual(ROL.tier_label(3, bands, paid_rate=0.0), "-")

    def test_posted_tier_rates_reads_the_exports_own_column(self):
        wes, _s = ROL.weekly_sales(self.cols, _crew(), TODAY)
        crew = _crew() + [
            _row(**{"spe.TN": "2145550120", "sp.Order Date (copy)": "11/4/2026", "Rep Tier Bonus Status": "30"}),
            _row(**{"spe.TN": "2145550121", "sp.Order Date (copy)": "11/5/2026", "Rep Tier Bonus Status": "50"}),
            _row(**{"spe.TN": "2145550122", "sp.Order Date (copy)": "11/5/2026", "Rep Tier Bonus Status": "110",
                    "DTR Status": "Shipped"}),                              # not posted: not counted
            _row(**{"spe.TN": "2145550123", "sp.Order Date (copy)": "11/5/2026", "Rep Tier Bonus Status": "110",
                    "spe.TN Type": "upgrade"})]                             # not a port line
        paid = ROL.posted_tier_rates(self.cols, crew, wes)
        self.assertEqual(paid[dt.date(2026, 11, 8)], {"Esmeralda Gonzalez": 50.0})     # tier week 11/1 - 11/7
        self.assertEqual(paid[dt.date(2026, 11, 22)], {})
        from automations.nds_metrics.run import Cols as _Cols
        k = HDR.index("Rep Tier Bonus Status")
        bare = _Cols(HDR[:k] + HDR[k + 1:])                                 # an export without the column
        self.assertEqual(ROL.posted_tier_rates(bare, [r[:k] + r[k + 1:] for r in crew], wes), {we: {} for we in wes})

    def test_page(self):
        esm = ROL.rep_lines(self.cols, _crew(), TODAY)["Esmeralda Gonzalez"]
        wes, sales = ROL.weekly_sales(self.cols, _crew(), TODAY)
        tier = ((dt.date(2026, 11, 15), dt.date(2026, 11, 21)), (6, 9))
        orders = dict(zip(wes, ((0, "-"), (4, "Tier 1"), (1, "-"), (3, "-"), (6, "Tier 2"))))
        page = ROL.html_for("Esmeralda Gonzalez", esm, TODAY, weekly=(wes, sales["Esmeralda Gonzalez"]), tier=tier,
                            orders=orders)
        bare = ROL.html_for("Esmeralda Gonzalez", esm, TODAY, weekly=(wes, sales["Esmeralda Gonzalez"]), tier=tier)
        self.assertNotIn("<th>Orders</th>", bare)                          # no tier counts -> the columns are left out
        self.assertIn('colspan="7">Sales by Week Ending', bare)
        self.assertIn("Activated Week 11.02 to 11.08", page)               # Carlos 11/20: "activated" next to "week"
        self.assertIn("Paid Friday 11.13", page)
        self.assertEqual(page.count(">Total</td>"), 2)                     # one per activated week, none under pending
        # a blank row after each grey Total: before the next blue band and before the orange band
        self.assertEqual(page.count('<tr class="gap"><td colspan="12"></td></tr>'), 2)
        self.assertIn('</tr><tr class="gap"><td colspan="12"></td></tr><tr><td class="band"', page)
        self.assertIn('</tr><tr class="gap"><td colspan="12"></td></tr><tr><td class="pdc"', page)
        self.assertLess(page.rindex(">Total</td>"), page.index("Pending / Disconnect / Cancel"))
        self.assertIn(">$66.90</td>", page)                                # 30% of 213 + the Extra plan's 10
        self.assertIn("<th>Device \u00b7 Phone \u00b7 Zip</th><th>Plan</th><th>Tier</th>", page)
        self.assertIn("iPhone 18 Pro - 256GB - Black<br><span class=\"dz\">214-555-0100 \u00b7 75060</span>", page)
        self.assertIn("<th>Tier</th><th>Est. Revenue</th><th>30% Payout</th><th>40% Payout</th>"
                      "<th>45% Payout</th><th>50% Payout</th></tr>", page)          # the money is far right
        for gone in ("Ported From", "SPM Number", "Wireless Order", ">BAN<", "<th>Package</th>", "<th>Next Up</th>",
                     "<th>Zip Code</th>", "<th>Phone Number</th>"):
            self.assertNotIn(gone, page)
        # the Activation/Pay Week box: 5 weeks, the current one last and highlighted (Carlos 11/20)
        cal = page[page.index("Activation/Pay Week"):page.index("Payout Levels")]
        import re
        self.assertEqual(len(re.findall(r'<tr><td class="[a-z]*">\d+/\d+/\d\d</td>', cal)), 5)
        self.assertIn("<th>Monday</th><th>Sunday</th><th>Friday</th>", cal)  # the deposit's weeks
        self.assertLess(cal.index('<td class="">10/19/26</td><td class="">10/25/26</td><td class="">10/30/26</td>'),
                        cal.index('<td class="now">11/16/26</td><td class="now">11/22/26</td><td class="now">11/27/26</td>'))
        self.assertNotIn("11/23/26", cal)                                  # nothing after the current week
        # the boxes
        for text in ("Payout Levels", ">Entry-level pay</td><td class=\"b\">30%</td>",
                     ">Leadership pay</td><td class=\"b\">40%</td>",
                     ">Leadership pay at 10 apps</td><td class=\"b\">45%</td>",      # Carlos 11/20 night: 10 / 14
                     ">Leadership pay at 14 apps</td><td class=\"b\">50%</td>"):
            self.assertIn(text, page)
        self.assertIn("Tier Bonus", page)
        for row in ("<td>Tier 1</td><td>4</td><td>$30</td>", '<td class="now">Tier 2</td><td class="now">5\u20136</td>'
                    '<td class="now">$50</td>', "<td>Tier 3</td><td>7\u20138</td><td>$75</td>",
                    "<td>Tier 4</td><td>9+</td><td>$110</td>"):
            self.assertIn(row, page)
        self.assertNotIn('class="note"', page)                             # no fine print under the boxes (Carlos 11/20)
        for fine in ("Highlighted = this week", "Week of 11/15", "Sales = apps", "week in progress"):
            self.assertNotIn(fine, page)
        self.assertIn('colspan="9">Sales by Week Ending (last 5 weeks)', page)
        # Orders + Tier right after the week ending (Carlos 11/20), revenue far right
        self.assertIn("<th>Week Ending</th><th>Orders</th><th>Tier</th><th>Sales</th>", page)
        self.assertIn("<th>Activation %</th><th>Est. Revenue</th></tr>", page)

        def cells(cls, *vals):
            return "".join('<td class="%s">%s</td>' % (cls, v) for v in vals)
        self.assertIn(cells("", "10/25", 0, "-", 1, 1, 0, 0, "100%", "$223"), page)
        self.assertIn(cells("alt", "11/1", 4, "Tier 1", 0, 0, 0, 0, "-", "$0"), page)
        self.assertIn(cells("", "11/8", 1, "-", 1, 1, 0, 0, "100%", "$223"), page)
        self.assertIn(cells("alt", "11/15", 3, "-", 3, 1, 1, 1, "33%", "$316"), page)
        self.assertIn(cells("now", "11/22", 6, "Tier 2", 1, 1, 0, 0, "100%", "$0"), page)

    def test_tier_box_marks_the_reps_band_only(self):
        week = (dt.date(2026, 11, 15), dt.date(2026, 11, 21))
        self.assertNotIn('class="now"', ROL.tier_box((week, (2, 3))))      # below the first band: nothing marked
        self.assertNotIn('class="now"', ROL.tier_box(None))                # the bands alone when the count is unavailable
        self.assertIn('<td class="now">Tier 3</td>', ROL.tier_box((week, (8, 20))))


class CrossCheck(unittest.TestCase):
    def test_rep_keys_and_the_deposit_sheet(self):
        self.assertEqual(ROL._rep_key("Jacob Isaiah Ortega"), ("jacob", "ortega"))
        self.assertEqual(ROL._rep_key("JACOB ORTEGA"), ("jacob", "ortega"))
        self.assertEqual(ROL._rep_key("Gary Van Whitaker II"), ("gary", "whitaker"))
        cs = [["Pick week ending →", "11.15"], [""], ["", "", "", "", "", "", "REP Name", "Sale Date", "Activation Date",
              "Description", "Product", "Description Detail", "Customer Name", "Total $ to ICD", "Commission"],
              ["", "", "", "", "", "", "Jacob Isaiah Ortega", "10/30/2026", "11/8/2026", "", "Port Line", "", "X", "$213.00", "$85.20"],
              ["", "", "", "", "", "", "Jacob Isaiah Ortega", "10/30/2026", "11/8/2026", "", "AT&T Unlimited Extra", "", "X", "$10.00", "$4.00"],
              ["", "", "", "", "", "", "Jacob Isaiah Ortega", "", "", "", "", "", "", "", "$89.20"],          # his subtotal row
              ["", "", "", "", "", "", "Nicholas Smedra", "11/1/2026", "11/9/2026", "", "Port Line", "", "Y", "$1,213.00", ""]]
        book = mock.Mock()
        book.worksheet.return_value.get_all_values.return_value = cs
        with mock.patch("automations.recruiting_report.fill.open_by_key", return_value=book):
            dep = ROL.deposit_by_rep(dt.date(2026, 11, 15), log=lambda *_a: None)
        book.worksheet.assert_called_once_with("CS 11.15")
        self.assertEqual(dep, {("jacob", "ortega"): 223.0, ("nicholas", "smedra"): 1213.0})


class ActiveReps(unittest.TestCase):
    def test_board_names_match_export_names(self):
        for board, export in (("Nick Smedra", "Nicholas Paul Smedra"),
                              ("Stefany Zaldivar", "Stefany Michelle Zaldivar Justiniano"),
                              ("Nathaly Benitez", "Nathaly Elizabeth Molina Benitez"),
                              ("Diego Borres", "Diego Javier Del Pozo Borres"),
                              ("Jacob Ortega", "Jacob Isaiah Ortega"), ("Cinthya Reyes", "Cinthya reyes"),
                              ("Jorge Hernandez", "Jorge Jose Hernandez Molina")):
            self.assertTrue(ROL.is_same_person(board, export), (board, export))
        self.assertFalse(ROL.is_same_person("Andrew De La Torre", "Aaron De La Torre"))
        self.assertFalse(ROL.is_same_person("Eduardo Alvarez", "Christopher Eduardo Cajabon Penagos"))

    def test_rep_dm_plan_gives_each_rep_only_their_own_picture(self):
        reps = ["Aaron De La Torre", "Andrew De La Torre", "Elisa Diaz-Garcia", "Cinthya reyes",
                "Isadora Bazan Puga", "Rodolfo Bazan", "Carlos Adriano Hidalgo"]
        plan = ROL.rep_dm_plan(reps, "aaron_torre=U0BMDU0MP7U, andrew_torre=U0C5ZE74892,"
                                     "elisa_diaz=U0CC8U1FN2W,cinthya_reyes=U04GRP800Q4,"
                                     "isadora_bazan=U0CDRUMEJ7Q,rodolfo_bazan=U0BQ3GB6RA4")
        self.assertEqual(plan, {"Aaron De La Torre": "U0BMDU0MP7U", "Andrew De La Torre": "U0C5ZE74892",
                                "Elisa Diaz-Garcia": "U0CC8U1FN2W", "Cinthya reyes": "U04GRP800Q4",
                                "Isadora Bazan Puga": "U0CDRUMEJ7Q", "Rodolfo Bazan": "U0BQ3GB6RA4"})
        self.assertNotIn("Carlos Adriano Hidalgo", plan)          # no key = not sent
        for bad in ("bazan=U0CDRUMEJ7Q",                     # two reps -> refuse
                    "zed_nobody=U0CDRUMEJ7Q",                # no rep -> refuse
                    "aaron_torre=U0BMDU0MP7U,aaron=U0BMDU0MP7U",  # two keys, one rep
                    "aaron_torre=Aaron"):                    # not a Slack id
            with self.assertRaises(ValueError, msg=bad):
                ROL.rep_dm_plan(reps, bad)

    def test_active_reps_skip_terminated_and_stop_at_totals(self):
        grid = [["", "", "Vantura"], ["WE", "11.22"], [""],
                ["#", "REP", "Current Week", "", "", "", "", "", "", "", "", "Campaign", "Trainer", "Field Status", "Team",
                 "Leadership Status", "Secondary Status"],
                ["1", "Aaron De La Torre", "3", "", "", "", "", "", "", "", "", "NDS", "", "", "", "Level 1"],
                ["2", "Brianna Belen Contreras", "0", "", "", "", "", "", "", "", "", "NDS", "", "", "", "Terminated"],
                ["3", "Carlos Hidalgo", "1", "", "", "", "", "", "", "", "", "NDS", "", "", "", "Mastermind", "Floater"],
                ["", "AT&T NDS", "70"], ["", "Last Week"], ["", "Zed Afterwards"]]
        book = mock.Mock()
        book.worksheet.return_value.get.return_value = grid
        with mock.patch("automations.recruiting_report.fill.open_by_key", return_value=book):
            self.assertEqual(ROL.active_board_reps(log=lambda *_a: None), ["Aaron De La Torre", "Carlos Hidalgo"])



class DailySend(unittest.TestCase):
    """Carlos 2026-11-23: "every morning send the reps the updated order log at 9am. send sebastian
    and i alll of them" -- launchd 9:00 + 9:20 on Lucy 2, `--rep-shot active --dm sheet --dm-reps sheet
    --daily`. Made-up names and ids: the real map lives on the control sheet, not in this repo."""
    SHOTS = {"Maria Elena Lopez": "/tmp/maria.png", "Juan Perez": "/tmp/juan.png", "Ana Ruiz": "/tmp/ana.png"}
    BOSSES = ["UBOSS0001", "UBOSS0002"]
    SPEC = "maria_lopez=UREP00001,juan_perez=UREP00002,gone_rep=UREP00009"

    def setUp(self):
        import tempfile
        from pathlib import Path as _P
        self.tmp = tempfile.TemporaryDirectory()
        self.state = _P(self.tmp.name) / "state.json"
        self.sent, self.logs = [], []

    def tearDown(self):
        self.tmp.cleanup()

    def dm(self, png, user, file_name, comment):
        self.sent.append((user, file_name, comment))

    def run_send(self, dm=None, **kw):
        kw.setdefault("everyone", self.BOSSES)
        kw.setdefault("spec", self.SPEC)
        kw.setdefault("daily", True)
        return ROL.send_shots(self.SHOTS, TODAY, dm=dm or self.dm, log=self.logs.append,
                              state_path=self.state, **kw)

    def test_sheet_rows_split_into_everyone_and_reps(self):
        rows = [["Key", "Slack ID", "Rep", "Note"], ["ALL", "UBOSS0001", "Boss One"], ["all", "UBOSS0002"],
                ["maria_lopez", "UREP00001", "Maria Elena Lopez"], ["", "UREP00003"], ["#old_rep", "UREP00004"],
                ["juan_perez", ""], ["juan_perez", " UREP00002 "]]
        self.assertEqual(ROL.slack_map_from_rows(rows),
                         (["UBOSS0001", "UBOSS0002"], "maria_lopez=UREP00001,juan_perez=UREP00002"))
        self.assertEqual(ROL.slack_map_from_rows([]), ([], ""))

    def test_lenient_plan_skips_a_bad_row_instead_of_refusing_everyone(self):
        problems = []
        plan = ROL.rep_dm_plan(list(self.SHOTS), self.SPEC + ",ana=UREP00005,ana_ruiz=UREP00006,x=bad",
                               problems=problems)
        self.assertEqual(plan, {"Maria Elena Lopez": "UREP00001", "Juan Perez": "UREP00002"})
        self.assertEqual(len(problems), 3)                       # gone_rep, Ana twice (both dropped), x=bad
        self.assertIn("gone_rep: no picture today", problems[0])
        with self.assertRaises(ValueError):                      # the one-off sends stay strict
            ROL.rep_dm_plan(list(self.SHOTS), self.SPEC)

    def test_each_rep_gets_only_their_own_and_the_bosses_get_all(self):
        self.assertEqual(self.run_send(), 0)
        got = {(u, f) for u, f, _c in self.sent}
        self.assertEqual(got, {(b, f) for b in self.BOSSES for f in ("maria.png", "juan.png", "ana.png")}
                         | {("UREP00001", "maria.png"), ("UREP00002", "juan.png")})
        ana = [c for u, f, c in self.sent if f == "ana.png"]
        self.assertTrue(all("not sent to the rep" in c for c in ana), ana)   # no Slack id: the bosses see it
        self.assertFalse(any("not sent" in c for u, f, c in self.sent if f != "ana.png"))
        self.assertTrue(ROL.daily_complete(TODAY, self.state))

    def test_once_a_day_the_retry_tick_sends_nothing_twice(self):
        self.run_send()
        n = len(self.sent)
        self.assertEqual(self.run_send(), 0)
        self.assertEqual(len(self.sent), n)
        self.assertFalse(ROL.daily_complete(TODAY + dt.timedelta(days=1), self.state))  # tomorrow starts fresh

    def test_a_failed_dm_is_retried_alone(self):
        def flaky(png, user, file_name, comment):
            if user == "UREP00002":
                raise RuntimeError("slack 500")
            self.dm(png, user, file_name, comment)
        self.assertEqual(self.run_send(dm=flaky), 1)
        self.assertFalse(ROL.daily_complete(TODAY, self.state))
        self.sent.clear()
        self.assertEqual(self.run_send(), 0)
        self.assertEqual([(u, f) for u, f, _c in self.sent], [("UREP00002", "juan.png")])
        self.assertTrue(ROL.daily_complete(TODAY, self.state))

    def test_dry_sends_nothing_and_keeps_no_state(self):
        self.assertEqual(self.run_send(dry=True), 0)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.state.exists())
        self.assertTrue(any("(dry): Juan Perez -> UREP00002" in m for m in self.logs), self.logs)
        self.assertIn("order log DMs planned (dry): 8", self.logs[-1])     # 3 x 2 bosses + 2 reps

    def test_a_boss_who_is_also_a_rep_gets_their_own_picture_once_and_no_note(self):
        spec = self.SPEC + ",ana_ruiz=UBOSS0001"                            # Ana is a boss AND a rep
        self.assertEqual(self.run_send(spec=spec), 0)
        ana = [(u, c) for u, f, c in self.sent if f == "ana.png"]
        self.assertEqual(sorted(u for u, _c in ana), ["UBOSS0001", "UBOSS0002"])   # not twice to UBOSS0001
        self.assertFalse(any("not sent" in c for _u, c in ana))
        self.assertNotIn("already", self.logs[-1])

    def test_a_second_send_running_stops(self):
        with ROL.daily_lock(self.state) as mine:
            self.assertTrue(mine)
            self.assertEqual(self.run_send(), 0)
        self.assertEqual(self.sent, [])

    def test_a_sheet_map_is_lenient_without_daily_too(self):
        self.assertEqual(self.run_send(daily=False, everyone=[], lenient=True), 0)   # gone_rep skipped
        self.assertEqual(sorted(u for u, _f, _c in self.sent), ["UREP00001", "UREP00002"])
        self.assertTrue(any("gone_rep: no picture today" in m for m in self.logs), self.logs)

    def test_one_off_refusal_still_sends_the_everyone_copies(self):
        self.assertEqual(self.run_send(daily=False, everyone=["UBOSS0001"]), 1)   # gone_rep -> refused
        self.assertEqual(sorted(f for u, f, _c in self.sent), ["ana.png", "juan.png", "maria.png"])
        self.assertEqual({u for u, _f, _c in self.sent}, {"UBOSS0001"})
        self.assertFalse(self.state.exists())


class DailySendCli(unittest.TestCase):
    def test_done_today_stops_before_any_pull(self):
        from automations.nds_metrics import run as R
        with mock.patch.object(ROL, "daily_complete", return_value=True), \
                mock.patch.object(R, "pull", side_effect=AssertionError("pulled")):
            self.assertEqual(R.main(["--rep-shot", "active", "--dm", "sheet", "--dm-reps", "sheet", "--daily",
                                     "--post"]), 0)

    def test_sheet_flags_read_who_gets_what_off_the_tab(self):
        from automations.nds_metrics import run as R
        shots = {"Juan Perez": "/tmp/juan.png"}
        with mock.patch.object(ROL, "daily_complete", return_value=False), \
                mock.patch.object(R, "pull", return_value="x.csv"), \
                mock.patch.object(R, "load_crew", return_value=(None, [])), \
                mock.patch.object(ROL, "build", return_value=shots) as build, \
                mock.patch.object(ROL, "sheet_slack_map", return_value=(["UBOSS0001"], "juan_perez=UREP00002")), \
                mock.patch.object(ROL, "send_shots", return_value=0) as send:
            self.assertEqual(R.main(["--rep-shot", "active", "--dm", "sheet", "--dm-reps", "sheet", "--daily",
                                     "--post"]), 0)
        self.assertTrue(build.call_args[1]["active_only"])
        self.assertEqual(send.call_args[1]["everyone"], ["UBOSS0001"])
        self.assertEqual(send.call_args[1]["spec"], "juan_perez=UREP00002")
        self.assertTrue(send.call_args[1]["daily"])
        self.assertFalse(send.call_args[1]["dry"])
        self.assertTrue(send.call_args[1]["lenient"])

    def test_unreadable_tab_sends_nothing(self):
        from automations.nds_metrics import run as R
        with mock.patch.object(ROL, "daily_complete", return_value=False), \
                mock.patch.object(R, "pull", return_value="x.csv"), \
                mock.patch.object(R, "load_crew", return_value=(None, [])), \
                mock.patch.object(ROL, "build", return_value={"Juan Perez": "/tmp/juan.png"}), \
                mock.patch.object(ROL, "sheet_slack_map", side_effect=RuntimeError("quota")), \
                mock.patch.object(ROL, "send_shots") as send:
            self.assertEqual(R.main(["--rep-shot", "active", "--dm", "sheet", "--dm-reps", "sheet", "--daily"]), 1)
        send.assert_not_called()

class SoldUnder(unittest.TestCase):
    """Carlos 11/20: this week's sales under Esmeralda's login, last week's under Sebastian's and the
    customer Sundararaghandran Viswanathan all belong to Jacob."""
    HDR = ["Rep", "sp.Order Date (copy)", "Customer Name"]
    RULES = [{"to": "Jacob Isaiah Ortega", "from": ["esmeralda", "gonzalez"], "start": dt.date(2026, 11, 16),
              "end": dt.date(2026, 11, 22), "customer": [], "date": None, "why": "stretch"},
             {"to": "Jacob Isaiah Ortega", "from": ["sebastian", "avellaneda"], "start": None, "end": None,
              "customer": [], "date": dt.date(2026, 11, 11), "why": "tab row 2"},
             {"to": "Jacob Isaiah Ortega", "from": ["aaron", "de", "la", "torre"], "start": None, "end": None,
              "customer": ["sundararaghandran", "viswanathan"], "date": None, "why": "tab row 8"}]

    def test_customer_matches_the_exports_short_name(self):
        full = ["sundararaghandran", "viswanathan"]
        self.assertTrue(ROL.customer_matches(full, "Sundararaghandran V"))
        self.assertTrue(ROL.customer_matches(full, "SUNDARARAGHANDRAN VISWANATHAN"))
        self.assertTrue(ROL.customer_matches(["juan", "diego", "gonzalez", "hernandez"], "JUAN DIEGO G"))
        self.assertFalse(ROL.customer_matches(full, "Sundararaghandran K"))
        self.assertFalse(ROL.customer_matches(full, "SUNDAR V"))
        self.assertFalse(ROL.customer_matches(full, "V"))
        self.assertFalse(ROL.customer_matches([], "RAGHAVAN G"))

    def test_real_seller(self):
        rs = lambda rep, day, cust: ROL.real_seller(self.RULES, rep, day, cust)
        self.assertEqual(rs("Esmeralda Gonzalez", dt.date(2026, 11, 19), "JARROD P"), "Jacob Isaiah Ortega")
        self.assertEqual(rs("Esmeralda Gonzalez", dt.date(2026, 11, 10), "MIRIAM R"), "")          # the week before: hers
        self.assertEqual(rs("Sebastian Pedro Avellaneda", dt.date(2026, 11, 11), "RAGHAVAN G"), "Jacob Isaiah Ortega")
        self.assertEqual(rs("Sebastian Pedro Avellaneda", dt.date(2026, 11, 18), "SOMEONE E"), "")
        self.assertEqual(rs("Aaron De La Torre", dt.date(2026, 11, 12), "Sundararaghandran V"), "Jacob Isaiah Ortega")
        self.assertEqual(rs("Aaron De La Torre", dt.date(2026, 11, 12), "OTHER C"), "")
        self.assertEqual(rs("Andrew De La Torre", dt.date(2026, 11, 12), "Sundararaghandran V"), "")  # a different rep
        self.assertEqual(rs("Jacob Isaiah Ortega", dt.date(2026, 11, 19), "ANY B"), "")              # already his
        only_date = [{"to": "X Y", "from": [], "start": None, "end": None, "customer": [], "date": dt.date(2026, 11, 11)}]
        self.assertEqual(ROL.real_seller(only_date, "Some Rep", dt.date(2026, 11, 11), "A B"), "")   # a date alone moves nothing

    def test_apply_moves_copies_and_spells_like_the_export(self):
        cols = Cols(self.HDR)
        rows = [["Esmeralda Gonzalez", "11/19/2026", "JARROD P"], ["Esmeralda Gonzalez", "11/10/2026", "MIRIAM R"],
                ["Sebastian Pedro Avellaneda", "11/11/2026", "RAGHAVAN G"], ["Aaron De La Torre", "11/12/2026", "Sundararaghandran V"],
                ["Jacob Isaiah Ortega", "10/30/2026", "SUNDARARAGHANDRAN V"]]
        short = [dict(r, to="Jacob Ortega") for r in self.RULES]                    # the tab may spell him short
        out, moved = ROL.apply_sold_under(cols, rows, short)
        self.assertEqual([r[0] for r in out], ["Jacob Isaiah Ortega", "Esmeralda Gonzalez", "Jacob Isaiah Ortega",
                                               "Jacob Isaiah Ortega", "Jacob Isaiah Ortega"])
        self.assertEqual(moved, {("Esmeralda Gonzalez", "Jacob Isaiah Ortega"): 1,
                                 ("Sebastian Pedro Avellaneda", "Jacob Isaiah Ortega"): 1,
                                 ("Aaron De La Torre", "Jacob Isaiah Ortega"): 1})
        self.assertEqual(rows[0][0], "Esmeralda Gonzalez")                           # the caller's rows are untouched
        self.assertEqual(ROL.apply_sold_under(cols, rows, []), (rows, {}))

    def test_a_moved_line_does_not_carry_the_logins_posted_tier(self):
        """build(): Aaron's login hit Tier 2 ($50 posted on its lines); the one order of his that is
        really Jacob's moves to Jacob with its payouts, but Jacob's tier stays his own count's."""
        cols = Cols(HDR)
        mk = lambda **kw: _row(**dict({"Rep": "Aaron De La Torre", "sp.Order Date (copy)": "11/12/2026",
                                       "DTR Active Date": "11/14/2026", "Rep Tier Bonus Status": "50"}, **kw))
        crew = [mk(**{"spe.TN": "21455502%02d" % n, "sp.SPM Number": "A%d" % n, "Customer Name": "OTHER %s" % "ABCDE"[n]})
                for n in range(4)]
        crew.append(mk(**{"spe.TN": "2145550299", "sp.SPM Number": "A9", "Customer Name": "Sundararaghandran V"}))
        rules = [{"to": "Jacob Isaiah Ortega", "from": ["aaron", "de", "la", "torre"], "start": None, "end": None,
                  "customer": ["sundararaghandran", "viswanathan"], "date": None, "why": "tab row 3"}]
        seen = {}

        def fake_render(rep, lines, today, out, weekly=None, tier=None, orders=None):
            seen[rep] = (len(lines), orders)
            return out
        import tempfile
        from pathlib import Path as _P
        with mock.patch("automations.nds_metrics.run.sow_rates", lambda: RATES), \
                mock.patch.object(ROL, "sold_under_rules", lambda log=print: rules), \
                mock.patch.object(ROL, "render_rep_png", fake_render), \
                mock.patch("automations.nds_metrics.double_tier.days", lambda seed, log=print: set()):
            ROL.build(cols, crew, TODAY, _P(tempfile.mkdtemp()), log=lambda *_a: None)
        we = dt.date(2026, 11, 15)                                         # tier week 11/8 - 11/14
        self.assertEqual(seen["Jacob Isaiah Ortega"][0], 1)                # the moved line is on Jacob's picture
        self.assertEqual(seen["Jacob Isaiah Ortega"][1][we], (1, "-"))     # 1 order: no tier, whatever Aaron's login earned
        self.assertEqual(seen["Aaron De La Torre"][0], 4)
        self.assertEqual(seen["Aaron De La Torre"][1][we], (4, "Tier 2"))  # his count is 4 now, Smart Circle posted $50

    def test_rules_come_from_payrolls_two_lists(self):
        from automations.vantura_payroll import run as VP
        tab = [["Customer", "Sale Date", "From Rep", "To Rep", "Note", "Added", "Last applied"],
               ["", "11/11/2026", "Sebastian Avellaneda", "Jacob Isaiah Ortega", "", "", ""],
               ["", "", "", "", "", "", ""],
               ["How it works: ...", "", "", "", "", "", ""],
               ["", "", "Nicholas Paul Smedra", "Nicholas Smedra", "rate fix", "", ""],          # spelling only: skipped
               ["Sundararaghandran Viswanathan", "", "Aaron De La Torre", "Jacob Isaiah Ortega", "", "", ""]]
        book = mock.Mock()
        book.worksheet.return_value.get_all_values.return_value = tab
        stretch = [("Esmeralda Gonzalez", "Jacob Isaiah Ortega", dt.date(2026, 11, 16), dt.date(2026, 11, 22), "why")]
        with mock.patch.object(VP, "SOLD_UNDER_PAYROLL", stretch), \
                mock.patch("automations.recruiting_report.fill.open_by_key", return_value=book) as opened:
            rules = ROL.sold_under_rules(log=lambda *_a: None)
        opened.assert_called_once_with(VP.SHEET_ID)
        book.worksheet.assert_called_once_with("Payroll Transfers")
        self.assertEqual([(r["to"], r["from"], r["start"], r["date"], r["customer"]) for r in rules],
                         [("Jacob Isaiah Ortega", ["esmeralda", "gonzalez"], dt.date(2026, 11, 16), None, []),
                          ("Jacob Isaiah Ortega", ["sebastian", "avellaneda"], None, dt.date(2026, 11, 11), []),
                          ("Jacob Isaiah Ortega", ["aaron", "de", "la", "torre"], None, None,
                           ["sundararaghandran", "viswanathan"])])
        with mock.patch.object(VP, "SOLD_UNDER_PAYROLL", stretch), \
                mock.patch("automations.recruiting_report.fill.open_by_key", side_effect=RuntimeError("sheets down")):
            self.assertEqual(len(ROL.sold_under_rules(log=lambda *_a: None)), 1)       # the stretches survive a dead tab


if __name__ == "__main__":
    unittest.main()
