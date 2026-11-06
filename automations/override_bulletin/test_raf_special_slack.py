"""python -m unittest automations.override_bulletin.test_raf_special_slack"""
import datetime as dt
import unittest

from automations.override_bulletin import raf_special_slack as R

# Real `Payout- Raf wow` crosstab, Period 7 (from the _raf_special_probe dump).
WOW = [
    ["", "Processed Week", "Processed Week", "Processed Week", "Processed Week"],
    ["", "6/21/2026", "6/28/2026", "7/5/2026", "7/12/2026"],
    ["New Fiber Estimate", "3,931", "4,404", "3,018", "4,350"],
    ["Override Estimate", "6,355", "6,728", "5,297", "6,466"],
    ["Raf Bonus Payout", "$6", "$6", "$5", "$6"],
    ["Raf Payout Total", "$38,130", "$40,368", "$26,485", "$38,796"],
]
TIERS = [["Tier and Payout"], ["**As of WE 6/14**"], ["Tier 1 : $4 | 1,800 "],
         ["Tier 2 : $5 | 2,800"], ["Tier 3 : $6 | 3,840 "]]


class T(unittest.TestCase):
    def test_parse_weeks(self):
        w = R.parse_weeks(WOW)
        v = w[dt.date(2026, 7, 5)]
        self.assertEqual((v["fiber"], v["units"], v["rate"], v["total"]),
                         (3018, 5297, 5, 26485))
        self.assertEqual(len(w), 4)

    def test_tiers(self):
        self.assertEqual(R.parse_tiers(TIERS),
                         [(1, 4.0, 1800), (2, 5.0, 2800), (3, 6.0, 3840)])

    def test_last_weeks_spans_periods_and_skips_unpaid(self):
        w = R.parse_weeks(WOW)
        w[dt.date(2026, 6, 14)] = {"total": 1.0}
        w[dt.date(2026, 7, 19)] = {"fiber": 10}          # no payout yet
        shown = R.last_weeks(w)
        self.assertEqual([d.day for d, _ in shown], [21, 28, 5, 12])

    def test_caption(self):
        cap = R.caption(R.last_weeks(R.parse_weeks(WOW)))
        self.assertIn("WE 7/12: *$38,796*", cap)
        self.assertIn("+$12,311 vs last week", cap)

    def test_picture_html(self):
        html = R.render_html(R.last_weeks(R.parse_weeks(WOW)), R.parse_tiers(TIERS))
        self.assertIn("$143,779", html)                   # 4-week total
        self.assertIn("$6 at 3,840+ New Fiber", html)
        self.assertIn("#d6f5dd", html)                    # $6 = top tier = green
        self.assertIn("#fff1c2", html)                    # $5 week (7/5) = amber

    def test_periods_window(self):
        self.assertEqual(R._periods(dt.date(2026, 11, 6)),
                         ["Period 10", "Period 11", "Period 12"])
        self.assertEqual(R._periods(dt.date(2026, 1, 6)), ["Period 1", "Period 2"])


if __name__ == "__main__":
    unittest.main()
