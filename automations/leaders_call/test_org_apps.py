"""org_apps: the cover-slide org total is found by LABEL and by DATE HEADER,
never by position — and a missing piece is a named LookupError, not a 0.

    python -m unittest automations.leaders_call.test_org_apps
"""
import datetime as dt
import unittest

from automations.leaders_call import org_apps as oa

# Shape of the live tab on 2026-09-21 (header row 22, ALL TOTALS row 23), with
# junk rows above so a position-based reader would miss.
GRID = [
    ["Product Summary - This Week", "", "Mon", "Tue"],
    ["Fiber", "", "10", "12"],
    [],
    ["ALPHALETE ORG", "", "WE 09.20", "WE 09.13", "WE 09.06", "WE 08.30"],
    ["ALL TOTALS", "", "4,403", "4319", "4115", "4458"],
    ["Raf Org", "", "1227", "1456", "1337", "1322"],
    ["Carlos Org", "", "1157", "1036", "1156", "1405"],
    ["Retail NL"],
    ["1", "Amjad Malhas", "129", "28", "13", "34"],
]


class OrgAppsFromGrid(unittest.TestCase):
    def test_newest_week_with_prior(self):
        r = oa.org_apps_from_grid(GRID, dt.date(2026, 9, 20))
        self.assertEqual((r.total, r.prev, r.delta), (4403, 4319, 84))
        self.assertEqual(oa.cover_lines(r),
                         ("4,403", "+84 vs 4,319 the week before"))

    def test_frozen_week_further_right(self):
        r = oa.org_apps_from_grid(GRID, dt.date(2026, 9, 6))
        self.assertEqual((r.total, r.prev), (4115, 4458))
        self.assertEqual(oa.cover_lines(r)[1], "-343 vs 4,458 the week before")

    def test_oldest_week_has_no_prior(self):
        r = oa.org_apps_from_grid(GRID, dt.date(2026, 8, 30))
        self.assertEqual((r.total, r.prev, r.delta), (4458, None, None))
        self.assertEqual(oa.cover_lines(r), ("4,458", ""))

    def test_week_not_on_board_is_named(self):
        with self.assertRaises(LookupError) as cm:
            oa.org_apps_from_grid(GRID, dt.date(2026, 9, 27))
        self.assertIn("WE 09.27", str(cm.exception))

    def test_missing_block_or_row_is_named(self):
        with self.assertRaises(LookupError):
            oa.org_apps_from_grid(GRID[:3], dt.date(2026, 9, 20))
        no_totals = [GRID[3], ["Raf Org", "", "1"]]
        with self.assertRaises(LookupError) as cm:
            oa.org_apps_from_grid(no_totals, dt.date(2026, 9, 20))
        self.assertIn("ALL TOTALS", str(cm.exception))

    def test_non_numeric_total_refuses(self):
        g = [GRID[3], ["ALL TOTALS", "", "#REF!", "4319"]]
        with self.assertRaises(LookupError):
            oa.org_apps_from_grid(g, dt.date(2026, 9, 20))


if __name__ == "__main__":
    unittest.main()
