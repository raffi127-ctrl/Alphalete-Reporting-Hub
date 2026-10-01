"""The captainship top-off only ever RAISES completed-day cells.

Austin Eldredge, 2026-10-01: Wednesday read 7 New Internet at the 05:20 fill and
16 in Tableau by mid-morning. The top-off must write 16 there — and must never
lower a cell or touch today, because a failed or filtered pull reads as 0.
"""
import datetime as dt
import unittest
from unittest import mock

from automations.org_sales_board import captainship as cap
from automations.org_sales_board import captainship_topoff as topoff

THU = dt.date(2026, 10, 1)
MON = dt.date(2026, 9, 28)


def _grid():
    g = [[""] * 12 for _ in range(4)]
    g[1][1], g[1][2], g[1][3], g[1][4] = "Austin Eldredge", "15", "17", "7"
    g[2][1], g[2][2], g[2][3], g[2][4] = "Pat Thompson", "30", "29", "16"
    return g


def _anchor():
    return cap.CaptainAnchor(captain="Pat", daily=[(2, "Austin Eldredge"),
                                                   (3, "Pat Thompson")],
                             day_cols=[3, 4, 5, 6, 7, 8, 9])


class PlanRaises(unittest.TestCase):
    def _plan(self, prog):
        with mock.patch.object(cap, "discover_captainships",
                               return_value=[("Pat's Captain Team", "fiber")]), \
             mock.patch.object(cap, "find_captainship_boxes",
                               return_value=[("new_internet", _anchor())]), \
             mock.patch("automations.org_sales_board.week.reporting_monday",
                        return_value=MON):
            return topoff.plan_raises(_grid(), prog, THU, aliases={})

    def test_late_sales_are_raised(self):
        prog = {"fiber": {"austin eldredge": {"NewInternet": {
            MON: 15, MON + dt.timedelta(1): 17, MON + dt.timedelta(2): 16}}}}
        ups, lines = self._plan(prog)
        self.assertEqual(ups, [{"range": "E2", "values": [[16]]}])
        self.assertIn("Austin Eldredge · Wed NI 7 -> 16", lines[0])

    def test_a_lower_or_missing_pull_writes_nothing(self):
        prog = {"fiber": {"austin eldredge": {"NewInternet": {MON: 3}}}}
        ups, _ = self._plan(prog)
        self.assertEqual(ups, [])          # Pat Thompson absent -> 0 -> no write
        ups, _ = self._plan({})            # every program failed
        self.assertEqual(ups, [])

    def test_today_is_never_written(self):
        prog = {"fiber": {"austin eldredge": {"NewInternet": {THU: 9}}}}
        ups, _ = self._plan(prog)
        self.assertEqual(ups, [])


class ResortScope(unittest.TestCase):
    def test_start_row(self):
        self.assertEqual(topoff._start_row("A230:L245"), 230)


if __name__ == "__main__":
    unittest.main()
