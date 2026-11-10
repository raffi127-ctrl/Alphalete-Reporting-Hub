"""Parse + render, offline. Rows copied from the custom view's real export
(Lucy 1, 2026-11-10).

    python -m unittest automations.nds_activation_rate.test_parse_render
"""
import datetime as dt
import unittest

from automations.nds_activation_rate import pull, sheet

HEADER = ["Owner Name", "Rep Name. ", "New/Port Trailing Act. Rate (10-19 Days)",
          "New/Port Trailing Act. Rate (20-29 Days)",
          "New/Port Trailing Act. Rate (30-60 Days)", ".", "0-30 Day Churn % ",
          "30 Day Churn %", "60 Day Churn %", "90 Day Churn %"]
ROWS = [HEADER,
        ["Grand Total", "Total", "70.3%", "77.8%", "78.6%", "", "3.9%", "", "", ""],
        ["Abdallah Ghousheh", "Total", "91.5%", "94.9%", "80.7%", "", "", "", "", ""],
        ["Abdallah Ghousheh", "Abdallah Ghousheh", "85.7%", "100.0%", "80.0%", "", "", "", "", ""],
        ["Abdallah Ghousheh", "Abdullah Alshawbaki", "", "", "", "", "", "", "", ""],
        ["Abdallah Ghousheh", "Andrew Couch", "", "", "100.0%", "", "", "", "", ""],
        ["", "Ali Alsarag", "71.4%", "75.0%", "75.0%", "", "", "", "", ""],
        ["Aaron Nimako", "Total", "", "", "", "", "", "", "", ""]]


class ParseRender(unittest.TestCase):
    def test_parse(self):
        d = pull.parse(ROWS)
        self.assertEqual(d["avg"]["10-19"], "70.3%")
        ag = d["owners"]["Abdallah Ghousheh"]
        self.assertEqual(ag["total"]["30-60"], "80.7%")
        # blank owner cell = same owner as the row above
        self.assertEqual(ag["reps"]["Ali Alsarag"]["10-19"], "71.4%")
        self.assertIn("Aaron Nimako", d["owners"])

    def test_missing_rep_column_is_loud(self):
        bad = [[h for h in HEADER if not h.startswith("Rep")]]
        with self.assertRaises(RuntimeError):
            pull.parse(bad)

    def test_log_and_render(self):
        d = pull.parse(ROWS)
        day = dt.date(2026, 11, 10)
        new = sheet.log_rows(day, "Khalil", d)
        reps = [r[3] for r in new]
        self.assertNotIn("Abdullah Alshawbaki", reps)       # no number anywhere
        grid = [sheet.LOG_HEADER] + new
        rows, kinds, n_days = sheet.render("Khalil", "Khalil Mansour", grid,
                                           list(d["owners"]))
        self.assertEqual(n_days, 1)
        flat = [r[:3] for r in rows]
        self.assertIn(["ACTIVATION 10-19 DAYS", "Rep", "Tue 11/10/26"], flat)
        self.assertIn(["Captainship Avg", "", "70.3%"], flat)
        self.assertIn(["Abdallah Ghousheh", "Owner total", "91.5%"], flat)
        # Andrew Couch only has 30-60: absent from the 10-19 box, present in 30-60
        b1019 = rows[rows.index(["ACTIVATION 10-19 DAYS", "Rep", "Tue 11/10/26"]):
                     rows.index(["ACTIVATION 20-29 DAYS", "Rep", "Tue 11/10/26"])]
        self.assertNotIn("Andrew Couch", [r[1] for r in b1019 if len(r) > 1])
        self.assertIn(["", "Andrew Couch", "100.0%"],
                      [r[:3] for r in rows[rows.index(
                          ["ACTIVATION 30-60 DAYS", "Rep", "Tue 11/10/26"]):]])


if __name__ == "__main__":
    unittest.main()
