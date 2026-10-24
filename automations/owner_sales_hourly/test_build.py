"""python -m unittest automations.owner_sales_hourly.test_build"""
from __future__ import annotations

import datetime as dt
import types
import unittest

from automations.owner_sales_hourly import run

DAY = dt.date(2026, 10, 24)


def _office(owner, campaign="att"):
    return types.SimpleNamespace(owner=owner, campaign=campaign)


class OwnerTotals(unittest.TestCase):
    def test_sums_reps_and_merges_an_owners_two_offices(self):
        relay = {
            "carlos-b2batt": {DAY: {"A": {"Int": 3, "Int Up": 1, "DTV": 0, "NL": 0}}},
            "carlos": {DAY: {"B": {"Sales": 2, "Volume": 9}}},
        }
        offices = {"carlos-b2batt": _office("Carlos Hidalgo", "b2b_att"),
                   "carlos": _office("Carlos Hidalgo", "b2b_box")}
        self.assertEqual(run.owner_totals(relay, offices, DAY),
                         {"Carlos Hidalgo": 6})

    def test_office_with_no_reading_today_is_left_off_not_zero(self):
        relay = {"rashad": {DAY - dt.timedelta(days=9): {"A": {"Int": 4}}},
                 "steve": {DAY: {}}}
        offices = {"rashad": _office("Rashad Reed"),
                   "steve": _office("Steve McElwee")}
        self.assertEqual(run.owner_totals(relay, offices, DAY),
                         {"Steve McElwee": 0})

    def test_unknown_key_uses_fallback_name(self):
        relay = {"rafael_hidalgo": {DAY: {"A": {"Int": 2}}}}
        self.assertEqual(run.owner_totals(relay, {}, DAY),
                         {"Rafael Hidalgo": 2})


def _grid():
    hdr = ["", "", "Monday", "Tuesday", "RUNNING WEEK TOTALS"]
    return [
        ["ATT Fiber Team"] + hdr[1:],
        ["", "", "19", "20", ""],
        ["", "Jacob Dover", "1", "2", "3"],
        ["", "Ryan Mcspadden", "0", "1", "1"],
        ["Totals", "", "1", "3", "4"],
        [""],
        ["", "RAFAEL HIDALGO CAPTAINSHIP TEAM"],
        ["Fiber - All Units"] + hdr[1:],
        ["", "", "19", "20", ""],
        ["", "Trang Canavan", "1", "1", "2"],
        ["Totals", "", "1", "1", "2"],
    ]


class OnlyOrg(unittest.TestCase):
    def test_top_boxes_only_not_captainship_blocks(self):
        org = run.org_owners(_grid())
        self.assertEqual(org, {"jacob dover", "ryan mcspadden"})

    def test_case_and_alias_match_and_outsiders_dropped(self):
        org = run.org_owners(_grid(), {"Jacob Dover": ["Jake Dover"]})
        kept, dropped = run.only_org(
            {"Jake Dover": 4, "Ryan McSpadden": 2, "Trang Canavan": 9}, org)
        self.assertEqual(kept, {"Jake Dover": 4, "Ryan McSpadden": 2})
        self.assertEqual(dropped, ["Trang Canavan"])


class Text(unittest.TestCase):
    def test_sorted_desc_with_total(self):
        now = dt.datetime(2026, 10, 24, 17, 50)
        text = run.build_text({"B": 5, "A": 5, "C": 9}, now)
        self.assertEqual(text.splitlines(), [
            "Owner Sales Today - 5:50 PM CT", "",
            "1. C 9", "2. A 5", "3. B 5", "", "🏆 TOTAL: 19"])

    def test_window(self):
        self.assertTrue(run.in_window(dt.datetime(2026, 10, 24, 21, 50)))
        self.assertFalse(run.in_window(dt.datetime(2026, 10, 24, 9, 50)))
        self.assertFalse(run.in_window(dt.datetime(2026, 10, 25, 15, 50)))


if __name__ == "__main__":
    unittest.main()
