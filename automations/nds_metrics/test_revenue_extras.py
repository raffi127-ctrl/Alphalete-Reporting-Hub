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

    def test_sales_per_rep(self):
        self.assertTrue(RX.reps_extra(19, 45).startswith(" <span"))     # rides after the count
        self.assertIn("2.4 sales per rep (45 sales this week)", RX.reps_extra(19, 45))
        self.assertIn("— sales per rep", RX.reps_extra(0, 0))


class Sales(unittest.TestCase):
    HDR = ["Rep", "sp.Order Date (copy)", "sp.SPM Number"]

    def test_distinct_orders_in_the_board_week(self):
        cols = R.Cols(self.HDR)
        rows = [["Ana", "11/9/2026", "DSI1"], ["Ana", "11/9/2026", "DSI1"],    # one order, two lines
                ["Ana", "11/11/2026", "DSI2"], ["Ben", "11/8/2026", "DSI3"],  # Sunday before: out
                ["Ben", "11/16/2026", "DSI4"],                                  # after today: out
                ["Cal", "11/12/2026", ""]]                                      # no SPM: still an order
        n = RX.board_sales(cols, rows, dt.date(2026, 11, 9), dt.date(2026, 11, 15), 1, 0, 2)
        self.assertEqual(n, 3)


if __name__ == "__main__":
    unittest.main()
