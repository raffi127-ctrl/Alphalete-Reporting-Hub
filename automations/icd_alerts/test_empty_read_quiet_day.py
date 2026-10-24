"""An empty credit-check list with no sale at the door is a slow day, not a fault.

2026-10-22/23: 17-18 offices a day landed in the hiccups thread as "a hiccup
reading SaraPlus" -- their grid showed every past day and nothing for today,
because they had not run a credit check yet. Eve: alarm only when the office
SOLD today and the list still comes back empty.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest

from automations.icd_alerts import post as P

DAY = dt.date(2026, 10, 23)


def _fault(stage="sweep-empty", office="tre"):
    return {"office": office, "stage": stage, "summary": "RuntimeError", "count": "7",
            "first": "09:03", "detail": "", "platform": "Darwin", "rownum": 5}


def _knocks(*offices):
    head = ["Office", "Day", "Rows JSON", "Tracker JSON", "Rep Count", "Received At"]
    rows = [head]
    for office, day, sales in offices:
        reps = [{"rep": "A", "sale": s} for s in sales]
        rows.append([office, day, json.dumps(reps), "[]", str(len(reps)), ""])
    return rows


class KnockSalesTest(unittest.TestCase):
    def test_sums_todays_sales_per_office(self):
        rows = _knocks(("tre", "2026-10-23", ["", "0"]),
                       ("hasani", "2026-10-23", ["1", "", "2"]),
                       ("aya", "2026-10-22", ["5"]))
        self.assertEqual(P.knock_sales_today(DAY, rows=rows), {"tre": 0, "hasani": 3})

    def test_a_sheets_date_display_still_matches(self):
        rows = _knocks(("hasani", "10/23/2026", ["1"]))
        self.assertEqual(P.knock_sales_today(DAY, rows=rows), {"hasani": 1})

    def test_unreadable_tab_is_none_not_zero(self):
        class Broken:
            def worksheet(self, name):
                raise RuntimeError("quota")
        self.assertIsNone(P.knock_sales_today(DAY, book=Broken()))


class QuietDayTest(unittest.TestCase):
    def test_no_sale_holds_it(self):
        self.assertTrue(P.empty_read_is_a_quiet_day(_fault(), {"tre": 0}))

    def test_no_knocks_row_at_all_holds_it(self):
        self.assertTrue(P.empty_read_is_a_quiet_day(_fault(), {}))

    def test_a_sale_today_posts_it(self):
        self.assertFalse(P.empty_read_is_a_quiet_day(_fault(office="hasani"), {"hasani": 1}))

    def test_knocks_key_differs_from_the_sara_key(self):
        self.assertFalse(P.empty_read_is_a_quiet_day(_fault(office="khalil-nds"), {"khalil": 2}))

    def test_unreadable_knocks_posts_it(self):
        """A broken tab must never silence a real empty read."""
        self.assertFalse(P.empty_read_is_a_quiet_day(_fault(), None))

    def test_other_stages_are_untouched(self):
        for st in ("sweep", "sweep-slow", "knocks", "box"):
            self.assertFalse(P.empty_read_is_a_quiet_day(_fault(stage=st), {}), st)


if __name__ == "__main__":
    unittest.main()
