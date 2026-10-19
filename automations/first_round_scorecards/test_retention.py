import datetime as dt
import unittest

from automations.first_round_scorecards import retention

HEAD = ["INTERVIEWER", "", "QUALIFIED", "2nd R BOOKED", "2nd R SHOWED"]
TODAY = dt.date(2026, 10, 19)


def block(label, rows, header=True):
    out = [[label, "", " INTERVIEWERS RETENTION (Interviewers breakdown)"],
           ["", "OFFICE", "WEEKLY TOTAL"], HEAD] if header else []
    return out + rows + [["AVERAGES", "", "1"]]


class ParseTest(unittest.TestCase):
    def test_weeks_newest_first_headerless_week_and_last_year(self):
        v = (block("10/11", [["Aya", "Candela", "9", "10", "6"], ["", "Ana", "1", "10", "4"]])
             + block("10/4", [["Raf", "Vicky", "1", "20", "11"]])
             + [["Raf", "Luisana", "1", "8", "4"]] + [["AVERAGES"]]   # 9/27, no header
             + block("12/28", [["Old", "X", "1", "50", "50"]]))          # no year: last year's
        w = retention.parse(v, TODAY)
        self.assertEqual([x["week"] for x in w],
                         [dt.date(2026, 10, 11), dt.date(2026, 10, 4), dt.date(2026, 9, 27),
                          dt.date(2025, 12, 28)])
        self.assertEqual((w[0]["booked"], w[0]["showed"]), (20, 10))
        self.assertEqual((w[2]["booked"], w[2]["showed"]), (8, 4))

    def test_rows_join_team_score_by_monday_and_change(self):
        ret = [{"week": dt.date(2026, 9, 20), "booked": 100, "showed": 60},
               {"week": dt.date(2026, 10, 4), "booked": 100, "showed": 58}]
        scores = {dt.date(2026, 10, 5): {"TEAM": {"avg": 57, "n": 1}}}
        lines = retention.rows(ret, scores)
        self.assertEqual(lines[0]["score"], 57)
        self.assertTrue(lines[0]["audits"])
        self.assertFalse(lines[1]["audits"])
        self.assertAlmostEqual(lines[0]["change"], -2)
        grid = retention.values(lines)
        self.assertIn("Before audits: 60.0%", grid[1][0])
        self.assertEqual(grid[3][0], "Oct 4 – Oct 10")
        self.assertEqual(grid[3][6], "▼ -2.0 pts")
        self.assertEqual(grid[3][5], 0.58)


if __name__ == "__main__":
    unittest.main()
