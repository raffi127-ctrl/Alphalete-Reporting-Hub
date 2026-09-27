"""App Avg columns on the Org Active Headcount tab (Rafael 2026-09-27).

Run: python -m unittest automations.org_active_headcount.test_app_avg
"""
import datetime as dt
import unittest

from automations.org_active_headcount import daily as d
from automations.org_active_headcount import email_send as E

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _pairs(xs):
    return [c for x in xs for c in (x, "App Avg")]


def _hc():
    """The tab after 9/27: every day and every week carries an 'App Avg'."""
    g = [
        ["", "ORG ACTIVE HEADCOUNT"],
        ["", "All Campaigns: Mon-Sun"] + DAYS,
        ["", "HC (Last Week)"] + ["1"] * 7,
        ["", "HC (4 Week AVG)"] + ["1"] * 7,
        [],
        ["All Campaings Ongoing Headcount", "", "WE 09.27", "App Avg", "WE 09.20", "App Avg"],
        [],
        ["1", "Rafael Hidalgo", "45", "", "50", "6.0"],
        ["2", "Ana Griffin", "0", "", "0", "0"],
        ["TOTALS", "", "45", "", "50", "6.0"],
        [],
        ["All Campaigns HC", ""] + _pairs(DAYS) + ["RUNNING WEEK TOTALS", "LAST WEEK'S TOTALS",
                                                  "PREVIOUS WEEK'S TOTALS"],
        ["", ""] + [str(n) for n in (21, 21, 22, 22, 23, 23, 24, 24, 25, 25, 26, 26, 27, 27)],
        ["1", "Rafael Hidalgo", "20", "", "40", "", "45", ""] + [""] * 8 + ["45", "50", "50"],
        ["2", "Ana Griffin", "0", "", "0", "", "0", ""] + [""] * 8 + ["0", "0", "0"],
        ["Totals", "", "20", "", "40", "", "45", ""] + [""] * 8 + ["45", "50", ""],
        ["WE 9.20", "", "30", "", "40"],
        [],
        ["All Campaings Ongoing Headcount", "", "by Wednesday", "", "", "App Avg", "", ""]
        + [c for x in DAYS for c in (x, "", "")],
        ["", "", "This week", "Last week", "Delta", "This week", "Last week", "Delta"]
        + ["This week", "Last week", "Delta"] * 7,
        ["1", "Rafael Hidalgo", "45", "50", "", "", "", ""] + ["20", "20", "", "40", "40", "", "45", "50", ""] + [""] * 12,
        ["2", "Ana Griffin", "0", "0", "", "", "", ""] + ["0", "0", "", "0", "0", "", "0", "0", ""] + [""] * 12,
        ["", "", "45", "50", "", "", "", ""] + ["20", "20", "", "40", "40", "", "45", "50", ""] + [""] * 12,
    ]
    return [list(r) for r in g]


def _ac():
    """The All Campaigns tab: its weekly block (for the week check), daily
    units, and a delta box with last week's units per day."""
    g = [
        ["AT&T FIBER TEAM", "", "WE 09.27"],
        ["All Units", ""] + DAYS + ["RUNNING WEEK TOTALS"],
        ["", ""] + [str(n) for n in range(21, 28)],
        ["1", "Rafael Hidalgo", "40", "60", "125", "", "", "", "", "225"],
        ["Totals", "", "40", "60", "125"],
        [],
        ["All Units - All Campaigns", "", "Total for week", "", ""] + [c for x in DAYS for c in (x, "", "")],
        ["", "", "Total this week", "Last week", "Delta"] + ["This week", "Last week", "Delta"] * 7,
        ["1", "Rafael Hidalgo", "225", "300", ""] + ["40", "50", "", "60", "70", "", "125", "180", ""] + [""] * 12,
    ]
    return [list(r) for r in g]


def _cells(ups):
    return dict(ups)


class AppAvgLayout(unittest.TestCase):
    def test_blocks_see_their_app_avg_columns(self):
        g = _hc()
        dl, og, dx = d.find_daily(g), d.find_ongoing(g), d.find_delta(g)
        self.assertEqual(dl["days"], [3, 5, 7, 9, 11, 13, 15])
        self.assertEqual(dl["avg"], [4, 6, 8, 10, 12, 14, 16])
        self.assertEqual(dl["run"], 17)
        self.assertEqual([c for c, _ in og["wcols"]], [3, 5])
        self.assertEqual(og["avg"], [4, 6])
        self.assertEqual((dx["week"], dx["avg"], dx["this"][0]), (3, 6, 9))

    def test_old_layout_has_no_app_avg(self):
        from automations.org_active_headcount.test_org_active_headcount import _hc_grid
        g = _hc_grid(week_cols=True)
        self.assertEqual(d.find_daily(g)["avg"], [None] * 7)
        self.assertEqual(d.plan_avgs(g, _ac()), [])

    def test_email_keeps_sunday_app_avg_and_the_week_check(self):
        g = _hc()
        self.assertTrue(E.board_range(g).startswith("A1:P"))
        self.assertEqual(E.delta_range(g), "A19:H23")
        self.assertEqual(E.totals_mismatch(g), [])

    def test_sort_ranks_the_delta_box_on_its_week_column(self):
        keys = [r["sortRange"]["sortSpecs"][0]["dimensionIndex"] + 1
                for r in d.sort_requests(1, _hc())]
        self.assertEqual(keys, [3, 17, 3])


class AppAvgValues(unittest.TestCase):
    def setUp(self):
        self.ups = _cells(d.plan_avgs(_hc(), _ac(), logfn=lambda *_: None))

    def test_daily_is_week_to_date_apps_over_that_days_heads(self):
        # Rafael: 40/20, (40+60)/40, (40+60+125)/45
        self.assertEqual((self.ups["D14"], self.ups["F14"], self.ups["H14"]), (2.0, 2.5, 5.0))

    def test_zero_heads_is_zero_average(self):
        self.assertEqual((self.ups["D15"], self.ups["H15"]), (0, 0))

    def test_ongoing_current_week_is_the_latest_day(self):
        self.assertEqual(self.ups["D8"], 5.0)
        self.assertEqual(self.ups["D10"], 5.0)

    def test_delta_compares_the_same_day_last_week(self):
        # last week to Wednesday: (50+70+180)/50 = 6.0 -> 5.0 vs 6.0
        self.assertEqual((self.ups["F21"], self.ups["G21"]), (5.0, 6.0))
        self.assertAlmostEqual(self.ups["H21"], -0.1667, places=4)

    def test_another_week_on_all_campaigns_computes_nothing(self):
        ac = _ac()
        ac[0][2] = "WE 10.04"
        self.assertEqual(d.plan_avgs(_hc(), ac, logfn=lambda *_: None), [])


class RollWithPairs(unittest.TestCase):
    def setUp(self):
        g = _hc()
        self.p = d.plan_roll(g, g, dt.date(2026, 9, 27), dt.date(2026, 10, 4))
        self.v = dict(self.p["values"])

    def test_weeks_move_two_columns(self):
        self.assertEqual((self.v["C6"], self.v["E6"], self.v["F6"], self.v["G6"]),
                         ("WE 10.04", "WE 09.27", "App Avg", "WE 09.20"))
        self.assertEqual((self.v["E8"], self.v["G8"], self.v["H8"]), ("45", "50", "6.0"))
        self.assertEqual(self.v["H10"], "6.0")           # average totals move too
        self.assertEqual(self.v["G10"], "=SUM(G8:G9)")

    def test_history_row_keeps_the_daily_total_average(self):
        self.assertEqual(self.p["stack_values"][:6], ["20", "", "40", "", "45", ""])
        self.assertEqual(self.p["stack_values"][-1], "45")   # RUNNING WEEK

    def test_clear_takes_the_averages_and_day_numbers_go_on_both(self):
        self.assertEqual(self.p["clear"], ["C14:P15"])
        self.assertEqual((self.v["C13"], self.v["D13"], self.v["P13"]), (28, 28, 4))

    def test_summary_reads_the_daily_day_columns(self):
        self.assertEqual(self.p["daily_days"], [3, 5, 7, 9, 11, 13, 15])


if __name__ == "__main__":
    unittest.main()
