# -*- coding: utf-8 -*-
"""NDS Revenue Board extras (Carlos 2026-11-15): tier chip, lines activated
($), port lines on the badge, the two cards, sales per rep.

  python -m unittest automations.nds_metrics.test_revenue_extras
"""
import datetime as dt
import unittest

from automations.nds_metrics import revenue_extras as RX
from automations.nds_metrics import run as R

BANDS = [(4, 30.0), (5, 50.0), (7, 75.0), (9, 110.0)]


class Chip(unittest.TestCase):
    def test_tier_names(self):
        self.assertEqual([RX.tier_name(n, BANDS) for n in (0, 3, 4, 5, 6, 7, 8, 9, 12)],
                         ["—", "—", "T1", "T2", "T2", "T3", "T3", "T4", "T4"])

    def test_badge_carries_the_port_lines(self):
        self.assertEqual(RX.rep_badge(5, 23), "5 orders · 23 port lines")
        self.assertEqual(RX.rep_badge(1, 1), "1 order · 1 port line")


class Row(unittest.TestCase):
    def test_lines_activated_replaces_the_port_lines_cell(self):
        cells, badge, tier = RX.row_extras(4, 13, (12, 2556.0), BANDS)
        self.assertEqual([c["text"] for c in cells],
                         ["12 ($2,556)", "✓ $390 now", "+1 → $700", "+3 → $1,200", "+5 → $1,980"])
        self.assertEqual(cells[0]["cls"], "ct")
        self.assertEqual(badge, "4 orders · 13 port lines")
        self.assertEqual(tier, "T1")

    def test_blank_zero_and_dollars_only(self):
        self.assertEqual(RX.activated_cell(None)["text"], "")        # source unreadable
        self.assertEqual(RX.activated_cell((0, 0.0))["text"], "0")
        self.assertEqual(RX.activated_cell((0, 93.0))["text"], "0 ($93)")   # Air only


class Activated(unittest.TestCase):
    RES = {"detail": [
        {"rep": "Ana Lopez", "line": "1", "bucket": "posted_this"},
        {"rep": "Ana Lopez", "line": "2", "bucket": "posted_this+can"},   # activated, died later: still activated
        {"rep": "Ana Lopez", "line": "3", "bucket": "posted_last"},
        {"rep": "Ana Lopez", "line": "4", "bucket": "open"},
        {"rep": "Ana Lopez", "line": "AIR", "bucket": "posted_this"},     # an install, not a line
        {"rep": "Ana Lopez", "line": "PROTECT", "bucket": "posted_this"},
        {"rep": "Ben Diaz", "line": "(order)", "bucket": "posted_this"},  # order-level: $ only
    ], "tables": {"this": {"rows": [{"rep": "Ana Lopez", "posted": 621},
                                    {"rep": "Ben Diaz", "posted": 213}]}}}

    def test_counts_wireless_lines_and_takes_the_table_dollars(self):
        self.assertEqual(RX.activated_this_week(self.RES),
                         {"Ana Lopez": (2, 621.0), "Ben Diaz": (0, 213.0)})

    def test_board_rep_matched_by_name(self):
        act = RX.activated_this_week(self.RES)
        self.assertEqual(RX.activated_for("Ana Maria Lopez", act), (2, 621.0))   # middle name on Tableau
        self.assertEqual(RX.activated_for("Ben Diaz", act), (0, 213.0))
        self.assertEqual(RX.activated_for("Cara Diaz", act), (0, 0.0))           # nothing activated
        self.assertIsNone(RX.activated_for("Cara Diaz", None))                   # source missing


class Cards(unittest.TestCase):
    def test_weeks_oldest_first(self):
        rows = [{"we": dt.date(2026, 10, 25), "rate": 0.772, "lines": 92},
                {"we": dt.date(2026, 11, 1), "rate": 0.71, "lines": 103},
                {"we": dt.date(2026, 11, 8), "rate": 0.55, "lines": 126},
                {"we": dt.date(2026, 11, 15), "rate": 0.0, "lines": 0}]
        html = RX.weeks_card(rows)
        self.assertIn("WE 10/25 <b>77%</b>", html)
        self.assertIn("WE 11/8 <b>55%</b>", html)
        self.assertIn("WE 11/15 <b>—</b>", html)
        self.assertLess(html.index("10/25"), html.index("11/8"))
        self.assertEqual(RX.weeks_card(None), "—")

    def test_churn(self):
        self.assertTrue(RX.churn_card({"act": 71, "disc": 3, "pend": 9}).startswith("4.2% "))
        self.assertIn("3 of 71 activated in the last 30 days", RX.churn_card({"act": 71, "disc": 3}))
        self.assertEqual(RX.churn_card({"act": 0, "disc": 0}), "—")
        self.assertEqual(RX.churn_card(None), "—")
        self.assertEqual([lab for lab, _v in RX.cards(None, None)],
                         ["ACTIVATION RATE BY WEEK-ENDING", "0–30 DAY CHURN · WIRELESS NON-BYOD"])

    def test_sales_per_rep_is_apps_per_rep(self):
        self.assertTrue(RX.reps_extra(19, 134).startswith(" <span"))    # rides after the count
        self.assertIn("7.1 sales per rep (134 apps this week)", RX.reps_extra(19, 134))
        self.assertIn("— sales per rep", RX.reps_extra(0, 0))


RATES = {"wireless": {"port_nonbyod": {"OOF": 213, "INFP": 193}, "port_byod": {"OOF": 188, "INFP": 168},
                      "new_line": 25, "upgrade_voice": 30, "tablet_wearable_nonbyod": 25},
         "internet_air": {"activation": 93, "auto_bill_pay_bonus": 30}}


def _rec(prod="WIRELESS", tn="port", device="iPhone 18 Pro - 256GB - Black", package="AT&T Extra 2.0",
         wt="Phone", wip="Pending", ifoof="OOF", abp="Y"):
    from automations.nds_churn import compute as NC
    return {"prod": NC.product_of(prod), "tn_type": tn, "device": device, "package": package,
            "wireless_type": wt, "wireless_ip": wip, "if_oof": ifoof, "abp": abp}


class Kinds(unittest.TestCase):
    def test_what_sold(self):
        self.assertEqual(RX.line_kind(_rec()), "new phone")                          # financed, ported
        self.assertEqual(RX.line_kind(_rec(wip="BYOD")), "byod")                    # the plan says so
        self.assertEqual(RX.line_kind(_rec(device="XT2215-1")), "byod")             # pending: bare model = own phone
        self.assertEqual(RX.line_kind(_rec(wip="Next36 w/o Next Up", device="SM-G991U")), "new phone")  # a plan beats the device rule
        self.assertEqual(RX.line_kind(_rec(prod="AIR", tn="", wt="Unknown", package="AT&T Internet Air")), "air")
        self.assertEqual(RX.line_kind(_rec(tn="new", wt="Wearable", device="Apple Watch Ultra 2")), "device")
        self.assertEqual(RX.line_kind(_rec(tn="new")), "new number")
        self.assertEqual(RX.line_kind(_rec(tn="upgrade")), "upgrade")
        self.assertEqual(RX.line_kind(_rec(prod="INTERNET")), "internet")

    def test_next_up_and_plan(self):
        self.assertTrue(RX.has_next_up(_rec(wip="Next36 w/ Next Up Anytime")))
        self.assertFalse(RX.has_next_up(_rec(wip="Next36 w/o Next Up")))
        self.assertFalse(RX.has_next_up(_rec(wip="Pending")))
        self.assertEqual([RX.plan_of(_rec(package=p)) for p in ("AT&T Premium 2.0", "AT&T Extra 2.0", "AT&T Value 2.0", "AT&T Internet Air")],
                         ["premium", "extra", "value", ""])


class Pricing(unittest.TestCase):
    def test_deposit_rates(self):
        self.assertEqual(RX.board_line_price(_rec(), RATES), 213)
        self.assertEqual(RX.board_line_price(_rec(ifoof="IF"), RATES), 193)
        self.assertEqual(RX.board_line_price(_rec(wip="BYOD"), RATES), 188)
        self.assertEqual(RX.board_line_price(_rec(wip="BYOD", ifoof="IF"), RATES), 168)
        self.assertEqual(RX.board_line_price(_rec(wip="BYOD", tn="new"), RATES), 25)     # own phone, new number
        self.assertEqual(RX.board_line_price(_rec(tn="new"), RATES), 25)
        self.assertEqual(RX.board_line_price(_rec(tn="upgrade"), RATES), 30)
        self.assertEqual(RX.board_line_price(_rec(tn="new", wt="Wearable"), RATES), 25)
        self.assertEqual(RX.board_line_price(_rec(prod="AIR", tn="", wt="Unknown", abp="Y"), RATES), 123)
        self.assertEqual(RX.board_line_price(_rec(prod="AIR", tn="", wt="Unknown", abp="N"), RATES), 93)
        self.assertEqual(RX.board_line_price(_rec(prod="INTERNET"), RATES), 0)


class Breakdown(unittest.TestCase):
    HDR = ["Rep", "sp.Order Date (copy)", "sp.SPM Number", "Product Type (Broken Out)", "spe.TN Type",
           "Device Description", "Package", "spe.Wireless Type", "Wireless Installment Plan", "IF/OOF", "Auto Bill Pay"]

    def _row(self, rep, od, spm, prod="WIRELESS", tn="port", dev="iPhone 18 Pro - 256GB - Black",
             pkg="AT&T Extra 2.0", wt="Phone", wip="Pending", ifoof="OOF", abp="Y"):
        return [rep, od, spm, prod, tn, dev, pkg, wt, wip, ifoof, abp]

    def test_apps_and_the_payout_variables(self):
        cols = R.Cols(self.HDR)
        rows = [self._row("Ana Lopez", "11/9/2026", "DSI1"),                                   # new phone, Extra
                self._row("Ana Lopez", "11/9/2026", "DSI1", wip="BYOD", pkg="AT&T Premium 2.0"),  # BYOD, Premium
                self._row("Ana Lopez", "11/9/2026", "DSI1", dev="XT2215-1", pkg="AT&T Value 2.0"),  # BYOD by device, Value
                self._row("Ana Lopez", "11/10/2026", "DSI2", wip="Next36 w/ Next Up Anytime"),  # new phone + Next Up
                self._row("Ana Lopez", "11/10/2026", "DSI2", tn="new", wt="Wearable", dev="Apple Watch"),  # device: not an app
                self._row("Ana Lopez", "11/11/2026", "DSI3", prod="AIR", tn="", wt="Unknown", pkg="AT&T Internet Air"),  # Air: an app
                self._row("Ben Diaz", "11/12/2026", "DSI4", ifoof="IF"),
                self._row("Ben Diaz", "11/8/2026", "DSI5"),                                    # Sunday before: out
                self._row("Ben Diaz", "11/16/2026", "DSI6")]                                   # after today: out
        idx = RX.column_index(cols)
        bd = RX.apps_breakdown(cols, rows, idx, 1, dt.date(2026, 11, 9), dt.date(2026, 11, 15))
        ana, off = bd["Ana Lopez"], bd[RX.OFFICE]
        self.assertEqual((ana["orders"], ana["apps"], ana["new phone"], ana["byod"], ana["air"], ana["device"]),
                         (3, 5, 2, 2, 1, 1))
        self.assertEqual((ana["nextup"], ana["premium"], ana["extra"], ana["value"]), (1, 1, 2, 1))
        self.assertEqual((off["orders"], off["apps"], off["new phone"]), (4, 6, 3))
        self.assertEqual(RX.badge(5, ana), "5 orders · 5 apps")
        self.assertEqual(RX.tags_html(ana), "2 new phones · 2 BYOD · 1 Air<br>1 Next Up · 1 Premium · 2 Extra · 1 Value")
        self.assertEqual(RX.badge(1, None), "1 order · 0 apps")
        self.assertEqual(RX.name_lines("Stefany Michelle Zaldivar Justiniano"), ["Stefany", "Michelle Zaldivar Justiniano"])
        self.assertEqual(RX.name_lines("Cher"), ["Cher"])
        # the same rows priced like the deposit
        total = sum(RX.board_line_price(RX.line_rec(cols, r, idx), RATES) for r in rows[:7])
        self.assertEqual(total, 213 + 188 + 188 + 213 + 25 + 123 + 193)


if __name__ == "__main__":
    unittest.main()
