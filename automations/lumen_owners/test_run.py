import datetime as dt
import unittest
from unittest import mock

from automations.lumen_owners import run as R

GRID = [
    ["ICD Owner [Office] (Nest)", "9/27/2026", "10/4/2026", "10/11/2026"],
    ["Nigel Marshall [VP Executives, Inc.] (Nest)", "210", "198", "40"],
    ["Lajahnik Valentine [Aventis Consulting, Inc.]", "12", "9", "1"],
    ["Somebody Else [Else LLC]", "5", "", ""],
    ["Grand Total", "227", "207", "41"],
]
TODAY = dt.date(2026, 10, 9)


def _cands(name, aliases):
    return {" ".join(name.casefold().split())}


class LumenOwnersTest(unittest.TestCase):
    def test_split_sales_key(self):
        self.assertEqual(R.split_sales_key("Nigel Marshall [VP Executives, Inc.] (Nest)"),
                         ("Nigel Marshall", "VP Executives, Inc."))
        self.assertEqual(R.split_sales_key("Plain Name"), ("Plain Name", ""))

    def test_weeks_are_finished_ones_newest_first(self):
        self.assertEqual(R.lumen_weeks(GRID, TODAY),
                         [dt.date(2026, 10, 4), dt.date(2026, 9, 27)])

    def test_rows_status_and_order(self):
        weeks = R.lumen_weeks(GRID, TODAY)
        lumen = R.lumen_by_owner(GRID, weeks)
        self.assertEqual(len(lumen), 3)                     # Grand Total dropped
        fiber = {"lajahnik valentine": {"Total": {TODAY: 4},
                                        "NewInternet": {TODAY: 3}}}
        with mock.patch("automations.org_sales_board.captainship."
                        "_candidates_for_name", _cands):
            rows = R.build_rows(lumen, fiber, {})
        self.assertEqual([(r["owner"], r["status"]) for r in rows], [
            ("Lajahnik Valentine", R.ON_ATT),
            ("Nigel Marshall", R.NOT_YET),                  # most Lumen first
            ("Somebody Else", R.NOT_YET),
        ])
        self.assertEqual((rows[0]["att_units"], rows[0]["att_ni"]), (4, 3))
        self.assertEqual(rows[1]["lumen"][dt.date(2026, 10, 4)], 198)
        self.assertIsNone(rows[2]["lumen"][dt.date(2026, 10, 4)])
        html = R.table_html(rows, weeks, "week of 10/05")
        self.assertIn("Not on AT&amp;T yet", html)
        self.assertIn("Lumen WE 10/4", html)

    def test_sales_board_boxes(self):
        mon = dt.date(2026, 10, 19)
        days = [mon + dt.timedelta(days=i) for i in range(7)]
        tue = days[1]
        rows = [
            {"owner": "Low", "att_days": {"Total": {mon: 1},
                                          "NewInternet": {}}},
            {"owner": "High", "att_days": {"Total": {mon: 2, tue: 3},
                                           "NewInternet": {tue: 2}}},
            {"owner": "Zero", "att_days": {"Total": {}, "NewInternet": {}}},
        ]
        h = R.sales_board_html(rows, days, tue, "week of 10/19")
        self.assertIn("NEW INTERNET", h)
        self.assertIn("ALL UNITS", h)
        allu = h.split("ALL UNITS", 1)[1]
        self.assertLess(allu.index("High"), allu.index("Low"))  # most first
        self.assertLess(allu.index("Low"), allu.index("Zero"))
        self.assertIn(">6</td></tr>", allu)                     # team total
        # Wed..Sun still ahead -> blank, not 0
        self.assertIn("<td %s></td>" % 'style="padding:5px 8px;border:1px solid '
                      '#ccc;font-size:12px;text-align:center"', allu)


if __name__ == "__main__":
    unittest.main()
