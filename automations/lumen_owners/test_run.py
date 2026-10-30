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
    def test_extra_owner_added_once_with_dashes(self):
        w = [dt.date(2026, 10, 25)]
        lumen = {"ISAIAH KELLUM [showtime]": {
            "owner": "ISAIAH KELLUM", "office": "showtime", "weeks": {w[0]: 77}}}
        out = R.add_extra_owners(lumen, w, extra=(
            ("Isaiah Kellum", "x"), ("Vaughn Osterhouse", "kingdom")))
        self.assertEqual(len(out), 2)               # Isaiah not doubled
        v = out["VAUGHN OSTERHOUSE [kingdom]"]
        self.assertEqual(v["owner"], "VAUGHN OSTERHOUSE")
        self.assertEqual(v["weeks"], {w[0]: None})  # dash, not a fake 0

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
        self.assertIn(">6</td><td", allu)                       # team total
        # Wed..Sun still ahead -> blank, not 0
        self.assertIn("<td %s></td>" % 'style="padding:5px 8px;border:1px solid '
                      '#ccc;font-size:12px;text-align:center"', allu)

    def test_sales_board_past_weeks(self):
        mon = dt.date(2026, 10, 19)
        days = [mon + dt.timedelta(days=i) for i in range(7)]
        rows = [
            {"owner": "A", "att_days": {"Total": {}, "NewInternet": {}},
             "att_past": {"Total": [7, None], "NewInternet": [2, None]}},
            {"owner": "B", "att_days": {"Total": {}, "NewInternet": {}},
             "att_past": {"Total": [5, None], "NewInternet": [1, None]}},
        ]
        h = R.sales_board_html(rows, days, mon, "week of 10/19")
        self.assertIn("Last Week Total<br>WE 10/18", h)
        self.assertIn("Prior Week Total<br>WE 10/11", h)
        allu = h.split("ALL UNITS", 1)[1]
        self.assertIn(">12</td><td", allu)          # team last week = 7 + 5
        self.assertIn("&ndash;", allu)              # failed week -> dash, not 0

    def test_build_rows_past(self):
        weeks = R.lumen_weeks(GRID, TODAY)
        lumen = R.lumen_by_owner(GRID, weeks)
        lw = {"nigel marshall": {"Total": {TODAY: 3}, "NewInternet": {TODAY: 1}}}
        with mock.patch("automations.org_sales_board.captainship."
                        "_candidates_for_name", _cands):
            rows = R.build_rows(lumen, {}, {}, [lw, None])
        nigel = next(r for r in rows if r["owner"] == "Nigel Marshall")
        self.assertEqual(nigel["att_past"]["Total"], [3, None])
        other = next(r for r in rows if r["owner"] == "Somebody Else")
        self.assertEqual(other["att_past"]["NewInternet"], [0, None])

    def test_status_words(self):
        self.assertEqual(R.status_for(0, 0, 0), R.NOT_YET)
        self.assertEqual(R.status_for(5, 3, 2), R.INT_WIRELESS)
        self.assertEqual(R.status_for(5, 5, 0), R.INT)
        self.assertEqual(R.status_for(4, 0, 4), R.WIRELESS_ONLY)
        self.assertEqual(R.status_for(2, 0, 0), R.ON_ATT)       # video only

    def test_rows_use_product_mix(self):
        weeks = R.lumen_weeks(GRID, TODAY)
        lumen = R.lumen_by_owner(GRID, weeks)
        fiber = {"nigel marshall": {"Total": {TODAY: 6}, "NewInternet": {}}}
        mix = {"nigel marshall": {"Wireless": {TODAY: 6}}}
        with mock.patch("automations.org_sales_board.captainship."
                        "_candidates_for_name", _cands):
            rows = R.build_rows(lumen, fiber, {}, None, mix)
        self.assertEqual(rows[0]["owner"], "Nigel Marshall")   # sellers first
        self.assertEqual(rows[0]["status"], R.WIRELESS_ONLY)

    def test_weeks_to_pull(self):
        tue = dt.date(2026, 10, 20)                  # week ends 10/25
        self.assertEqual(R.weeks_to_pull({}, tue), list(range(1, 10)))
        have = {dt.date(2026, 10, 25) - dt.timedelta(days=7 * i): {}
                for i in range(10)}
        self.assertEqual(R.weeks_to_pull(have, tue), [1, 2])

    def test_week_ok(self):
        ref = dt.date(2026, 10, 13)                 # week 10/12-10/18
        self.assertTrue(R._week_ok({"x": {"Total": {dt.date(2026, 10, 14): 1}}}, ref))
        self.assertFalse(R._week_ok({"x": {"Total": {dt.date(2026, 10, 20): 1}}}, ref))



class RecipientsTest(unittest.TestCase):
    def test_to_flag_wins(self):
        self.assertEqual(R.recipients("a@x.com, b@x.com", expand=lambda g: 1 / 0),
                         ["a@x.com", "b@x.com"])

    def test_send_goes_to_the_group(self):
        seen = []
        def exp(groups):
            seen.append(groups)
            return ["chan@x.com", "raf@x.com"], []
        self.assertEqual(R.recipients("", expand=exp), ["chan@x.com", "raf@x.com"])
        self.assertEqual(seen, [["Lumen Owners"]])

    def test_unreadable_or_missing_group_falls_back(self):
        def boom(groups):
            raise RuntimeError("no token")
        self.assertEqual(R.recipients("", expand=boom), R.FALLBACK_TO)
        self.assertEqual(R.recipients("", expand=lambda g: ([], ["Lumen Owners"])),
                         R.FALLBACK_TO)
        self.assertIn(R.RAF, R.FALLBACK_TO)


if __name__ == "__main__":
    unittest.main()


class PrettyNameTest(unittest.TestCase):
    def test_caps_become_initial_caps(self):
        from automations.lumen_owners.run import pretty_name
        self.assertEqual(pretty_name("NIGEL MARSHALL"), "Nigel Marshall")
        self.assertEqual(pretty_name("STEVE McElwee"), "Steve McElwee")
        self.assertEqual(pretty_name("Aaron Nimako"), "Aaron Nimako")
