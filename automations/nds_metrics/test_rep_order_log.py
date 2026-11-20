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
       "Product Type (Broken Out)", "spe.Install Date", "IF/OOF", "Auto Bill Pay", "Rep Tier Bonus Status"]
TODAY = dt.date(2026, 11, 20)                       # Friday; its Mon-Sun week ends Sun 11/22


def _row(**kw):
    base = dict(zip(HDR, ["Esmeralda Gonzalez", "11/3/2026", "11/5/2026", "FELIPE C", "Posted", "Delivered",
                          "iPhone 18 Pro - 256GB - Black", "AT&T Extra 2.0", "Next36 w/ Next Up Anytime",
                          "2145550100", "75060", "T-MOBILE USA", "port", "DSI1", "177145738935", "Phone",
                          "WIRELESS", "", "OOF", "", "0"]))
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
        # 11/20: Ported From / SPM Number / Wireless Order # / BAN gone; "Package" is headed "Plan" and sits
        # next to Next Up; Est. Revenue + the four payout columns close the table, far right
        self.assertEqual(ROL.COLUMNS, ("Order Date", "Activation Date", "Customer Name", "Status",
                                       "Device", "Plan", "Next Up", "Phone Number", "Zip Code", "Est. Revenue",
                                       "30% Payout", "40% Payout", "45% Payout", "50% Payout"))

    def test_payouts_and_totals(self):
        self.assertEqual(ROL.payouts(213), {"30% Payout": 63.9, "40% Payout": 85.2, "45% Payout": 95.85,
                                            "50% Payout": 106.5})
        self.assertEqual(ROL.payouts(0), {"30% Payout": 0.0, "40% Payout": 0.0, "45% Payout": 0.0, "50% Payout": 0.0})
        lines = [dict({"Est. Revenue": r}, **ROL.payouts(r)) for r in (213, 188, 25)]
        self.assertEqual(ROL.totals(lines), {"Est. Revenue": 426.0, "30% Payout": 127.8, "40% Payout": 170.4,
                                             "45% Payout": 191.7, "50% Payout": 213.0})
        row = ROL.total_row(lines)
        self.assertIn('colspan="9">Total</td>', row)                       # label spans Order Date..Zip Code
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
        self.assertEqual(wes, [dt.date(2026, 10, 25), dt.date(2026, 11, 1), dt.date(2026, 11, 8), dt.date(2026, 11, 15),
                               dt.date(2026, 11, 22)])                                            # 5 weeks (Carlos 11/20)
        esm = sales["Esmeralda Gonzalez"]
        self.assertEqual(dict(esm[dt.date(2026, 10, 25)]), {"sold": 1, "activated": 1, "revenue": 213.0})   # the 10/20 port
        self.assertEqual(dict(esm[dt.date(2026, 11, 8)]), {"sold": 1, "activated": 1, "revenue": 213.0})    # 11/3 port, posted
        # WE 11/15: the BYOD (pending, 188), the cancelled port (0), the Air (active, 93) are the apps; the
        # tablet (25) is not an app but its money is in the week's revenue
        self.assertEqual(dict(esm[dt.date(2026, 11, 15)]),
                         {"sold": 3, "pending": 1, "cancelled": 1, "activated": 1, "revenue": 306.0})
        self.assertEqual(dict(esm[dt.date(2026, 11, 22)]), {"sold": 1, "activated": 1, "revenue": 193.0})   # disconnected after activating, in footprint
        self.assertNotIn(dt.date(2026, 11, 1), esm)                                               # nothing sold that week
        wes4, _s = ROL.weekly_sales(self.cols, _crew(), TODAY, weeks=4)
        self.assertEqual(wes4[0], dt.date(2026, 11, 1))

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
        bare = _Cols(HDR[:-1])                                              # an export without the column
        self.assertEqual(ROL.posted_tier_rates(bare, [r[:-1] for r in crew], wes), {we: {} for we in wes})

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
        self.assertIn("Activated Week 11.01 to 11.07", page)               # Carlos 11/20: "activated" next to "week"
        self.assertIn("Paid Friday 11.13", page)
        self.assertEqual(page.count(">Total</td>"), 2)                     # one per activated week, none under pending
        # a blank row after each grey Total: before the next blue band and before the orange band
        self.assertEqual(page.count('<tr class="gap"><td colspan="14"></td></tr>'), 2)
        self.assertIn('</tr><tr class="gap"><td colspan="14"></td></tr><tr><td class="band"', page)
        self.assertIn('</tr><tr class="gap"><td colspan="14"></td></tr><tr><td class="pdc"', page)
        self.assertLess(page.rindex(">Total</td>"), page.index("Pending / Disconnect / Cancel"))
        self.assertIn(">$63.90</td>", page)
        self.assertIn("<th>Plan</th><th>Next Up</th>", page)
        self.assertIn("<th>Zip Code</th><th>Est. Revenue</th><th>30% Payout</th><th>40% Payout</th>"
                      "<th>45% Payout</th><th>50% Payout</th></tr>", page)          # the money is far right
        for gone in ("Ported From", "SPM Number", "Wireless Order", ">BAN<", "<th>Package</th>"):
            self.assertNotIn(gone, page)
        # the Activation/Pay Week box: 5 weeks, the current one last and highlighted (Carlos 11/20)
        cal = page[page.index("Activation/Pay Week"):page.index("Payout Levels")]
        import re
        self.assertEqual(len(re.findall(r'<tr><td class="[a-z]*">\d+/\d+/\d\d</td>', cal)), 5)
        self.assertLess(cal.index('<td class="">10/18/26</td><td class="">10/24/26</td><td class="">10/30/26</td>'),
                        cal.index('<td class="now">11/15/26</td><td class="now">11/21/26</td><td class="now">11/27/26</td>'))
        self.assertNotIn("11/22/26", cal)                                  # nothing after the current week
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
        self.assertNotIn('class="note"', page)                             # no fine print under the boxes (Carlos 11/20)
        for fine in ("Highlighted = this week", "Week of 11/15", "Sales = apps", "week in progress"):
            self.assertNotIn(fine, page)
        self.assertIn('colspan="9">Sales by Week Ending (last 5 weeks)', page)
        # Orders + Tier right after the week ending (Carlos 11/20), revenue far right
        self.assertIn("<th>Week Ending</th><th>Orders</th><th>Tier</th><th>Sales</th>", page)
        self.assertIn("<th>Activation %</th><th>Est. Revenue</th></tr>", page)

        def cells(cls, *vals):
            return "".join('<td class="%s">%s</td>' % (cls, v) for v in vals)
        self.assertIn(cells("", "10/25", 0, "-", 1, 1, 0, 0, "100%", "$213"), page)
        self.assertIn(cells("alt", "11/1", 4, "Tier 1", 0, 0, 0, 0, "-", "$0"), page)
        self.assertIn(cells("", "11/8", 1, "-", 1, 1, 0, 0, "100%", "$213"), page)
        self.assertIn(cells("alt", "11/15", 3, "-", 3, 1, 1, 1, "33%", "$306"), page)
        self.assertIn(cells("now", "11/22", 6, "Tier 2", 1, 1, 0, 0, "100%", "$193"), page)

    def test_tier_box_marks_the_reps_band_only(self):
        week = (dt.date(2026, 11, 15), dt.date(2026, 11, 21))
        self.assertNotIn('class="now"', ROL.tier_box((week, (2, 3))))      # below the first band: nothing marked
        self.assertNotIn('class="now"', ROL.tier_box(None))                # the bands alone when the count is unavailable
        self.assertIn('<td class="now">Tier 3</td>', ROL.tier_box((week, (8, 20))))


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
