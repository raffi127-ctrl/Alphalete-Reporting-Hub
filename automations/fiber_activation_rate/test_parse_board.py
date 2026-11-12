"""Offline: parse the Metrics crosstab shape + build the board HTML.

    python -m unittest automations.fiber_activation_rate.test_parse_board
"""
import datetime as dt
import unittest

from automations.fiber_activation_rate import run, slack_board

H = ["Captain's Bonus Teams", "ICD Owner Name (rep)", "Rep Name",
     "Rolling 4 Weeks", "30-60 day New Internet activation rate", "Other"]
ROWS = [H,
        ["Sahil's Team", "Haytham Nagi", "Total", "81.0%", "84.2%", "x"],
        ["", "", "Zachery Boren", "90.0%", "100.0%", ""],
        ["", "", "Drake Lambert", "", "", ""],          # no number -> dropped
        ["", "Other Owner", "Total", "70.0%", "", ""],
        ["", "", "Some Rep", "", "75.0%", ""],
        ["", "Total", "Total", "80.0%", "80.0%", ""],     # team avg -> skipped
        ["Grand Total", "", "", "79.0%", "81.0%", ""]]


class T(unittest.TestCase):
    def test_parse(self):
        d = run.parse(ROWS)
        self.assertEqual(set(d), {"Haytham Nagi", "Other Owner"})
        h = d["Haytham Nagi"]
        self.assertEqual(h["team"], "Sahil's Team")
        self.assertEqual(h["reps"]["Total"], {"0-30": "81.0%", "30-60": "84.2%"})
        self.assertIn("Zachery Boren", h["reps"])
        self.assertNotIn("Drake Lambert", h["reps"])
        self.assertEqual(d["Other Owner"]["reps"]["Some Rep"]["30-60"], "75.0%")

    def test_missing_rep_col_is_loud(self):
        with self.assertRaises(ValueError):
            run.parse([[c for c in H if c != "Rep Name"]])

    def test_log_and_board(self):
        day = dt.date(2026, 11, 12)
        grid = [run.LOG_HEADER] + run.log_rows(day, run.parse(ROWS))
        self.assertEqual(grid[1][2:4], ["Haytham Nagi", "Total"])  # Total first
        owner, reps = slack_board.load_owner(grid, "haytham  nagi")
        html = slack_board.build_html("0-30", owner, slack_board.last_days(reps), reps)
        self.assertIn("Zachery Boren", html)
        self.assertIn("#93C47D", html)      # 90% green
        self.assertIn("#D9D9D9", html)      # 81% grey on 0-30
        html = slack_board.build_html("30-60", owner, slack_board.last_days(reps), reps)
        self.assertNotIn("#D9D9D9;", html)  # no grey band on 30-60


if __name__ == "__main__":
    unittest.main()
