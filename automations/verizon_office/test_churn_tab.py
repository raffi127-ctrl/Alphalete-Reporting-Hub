import datetime as dt
import tempfile
import unittest
from pathlib import Path

import openpyxl

from automations.verizon_office import churn_tab as CT
from automations.verizon_office.test_order_log_tab import BASE_COLS

TODAY = dt.date(2026, 11, 15)


def _line(rep, signed, cat, code, cur, cancel, act, order, line, pname, item, sku, port):
    return [rep, signed, cat, code, cur, cancel, act, order, line, pname, item, sku, port, "", ""]


def _file():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Order Detail"
    ws.append(BASE_COLS + ["CustomerName", "StatusReason"])
    D = dt.datetime
    rows = [
        # port, activated 10/20, disconnected 11/01 -> in the 30-day window, dead, falls off 11/19 (4d)
        _line("Will Bautista", D(2026, 10, 18), "Wireless Line", "CAN", "Disc. Post", D(2026, 11, 1), D(2026, 10, 20), "Q_1", "1", "Wireless Line - New", "IP17", "NEW", "Y") + ["ANA R", "Customer request"],
        # port, activated 10/25, active
        _line("Will Bautista", D(2026, 10, 22), "Wireless Line", "APPR", "Activated", None, D(2026, 10, 25), "Q_2", "1", "Wireless Line - New", "IP17", "NEW", "Y") + ["BOB S", ""],
        # byod, activated 11/02, active
        _line("Diego Chacon", D(2026, 11, 1), "Wireless Line", "APPR", "Activated", None, D(2026, 11, 2), "Q_3", "1", "Wireless Line - Byod", "BYOD", "BYOD", "Y") + ["CAL T", ""],
        # byod, activated 11/05, disconnected 11/10 -> dead in window, falls off 12/05 (20d)
        _line("Diego Chacon", D(2026, 11, 3), "Wireless Line", "CAN", "Disc. Pre", D(2026, 11, 10), D(2026, 11, 5), "Q_4", "1", "Wireless Line - Byod", "BYOD", "BYOD", "N") + ["DEE U", "Non-pay"],
        # activated 9/30 -> OUTSIDE the 30-day window
        _line("Diego Chacon", D(2026, 9, 28), "Wireless Line", "APPR", "Activated", None, D(2026, 9, 30), "Q_5", "1", "Wireless Line - New", "IP17", "NEW", "Y") + ["EVE V", ""],
        # sold 11/12, pending (not activated)
        _line("Will Bautista", D(2026, 11, 12), "Wireless Line", "APPR", "Submitted", None, None, "Q_6", "1", "Wireless Line - New", "IP17", "NEW", "Y") + ["FAY W", ""],
        # sold 11/13, cancelled never activated
        _line("Will Bautista", D(2026, 11, 13), "Wireless Line", "REJ", "", D(2026, 11, 14), None, "Q_7", "1", "Wireless Line - New", "IP17", "NEW", "N") + ["GUS X", ""],
    ]
    for r in rows:
        ws.append(r)
    p = Path(tempfile.mkdtemp()) / "sv.xlsx"
    wb.save(p)
    return p


class ChurnTabTest(unittest.TestCase):
    def setUp(self):
        self.sv = _file()
        self.lines = CT.OL.lines(self.sv)

    def test_box_counts_rolling_30_days(self):
        s = CT.churn_summary(self.lines, TODAY)
        self.assertEqual((s["All Lines"]["base"], s["All Lines"]["disc"]), (4, 2))      # 9/30 one is out
        self.assertAlmostEqual(s["All Lines"]["rate"], 0.5)
        self.assertEqual(list(s), ["All Lines"])                                         # one churn, no port/BYOD split
        self.assertEqual(s["All Lines"]["pending"], 1)                                   # 11/12 submitted; the REJ one is cancelled

    def test_rolloff_soonest_first_with_pct_after(self):
        roll = CT.rolloff_rows(self.lines, TODAY)
        self.assertEqual([(r["customer"], r["kind"]) for r in roll], [("Ana R", "port"), ("Dee U", "BYOD")])
        a = roll[0]
        self.assertEqual((a["days_left"], a["falloff"], a["reason"]), (4, dt.date(2026, 11, 19), "Customer request"))
        # once Ana (10/20) ages off, the window holds Bob 10/25 (alive), Cal 11/02 (alive), Dee 11/05 (dead) -> 1/3
        self.assertAlmostEqual(a["pct_all"], 1 / 3)
        self.assertEqual(roll[1]["days_left"], 20)
        self.assertTrue(roll[1]["quick"] and not a["quick"])

    def test_activation_rates_by_order_age(self):
        office, reps = CT.activation_rates(self.lines, TODAY)
        # 0-30 by ORDER date: Q_1 (10/18, 28d, disconnected=activated), Q_2, Q_3, Q_4, Q_6 (pending), Q_7 (cancelled)
        self.assertEqual((office["0-30"]["activated"], office["0-30"]["sold"]), (4, 6))
        self.assertEqual((office["31-60"]["activated"], office["31-60"]["sold"]), (1, 1))  # Q_5 9/28 = 48d
        self.assertEqual((reps["Diego Chacon"]["0-30"]["activated"], reps["Diego Chacon"]["0-30"]["sold"]), (2, 2))

    def test_credico_tier_neutral_under_15(self):
        t = CT.credico_tier(self.sv, TODAY)
        self.assertEqual((t["tier"], t["pay"]), (4, 190))
        # 11/15 sits in the block that began 10/25, scored on the 8/25-9/23 window (comp.CHURN_CALENDAR)
        self.assertEqual(t["window"], (dt.date(2026, 8, 25), dt.date(2026, 9, 23)))
        self.assertIn("neutral", t["why"])

    def test_grid_shape(self):
        grid, marks = CT.build_grid(self.lines, TODAY, CT.credico_tier(self.sv, TODAY))
        self.assertEqual(grid[0][0], CT.TITLE)
        self.assertTrue(all(len(r) == 18 for r in grid))
        self.assertEqual(len(marks["tier_rows"]), 8)
        tiers = [grid[r - 1][7:11] for r in marks["tier_rows"]]
        self.assertEqual(tiers[0], ["Tier 1", "0 – 4.99%", "$237", ""])
        self.assertEqual(tiers[3][3], "◀ now")
        self.assertIn("OFFICE TOTAL (all reps)", [r[15] for r in grid])
        self.assertEqual(len(marks["quick_rows"]), 1)          # Dee: 11/05 -> 11/10 (5 days); Ana 12 days is not red
        self.assertNotIn(CT.TAB, CT.PROTECTED_TABS)


if __name__ == "__main__":
    unittest.main()
