"""python -m unittest automations.interviewers_retention.test_build"""
import datetime as dt
import unittest
from types import SimpleNamespace

from automations.interviewers_retention import build

HDR = ["INTERVIEWER", "", "QUALIFIED", "2nd R BOOKED", "2nd R SHOWED", "2nd SHOWED %"]
TODAY = dt.date(2026, 11, 11)


def box(label, rows):
    out = [[label, "", " INTERVIEWERS RETENTION (Interviewers breakdown)"],
           ["", "OFFICE", "WEEKLY TOTAL"], HDR]
    out += rows
    out.append(["AVERAGES", "", "99", "999", "999"])
    return out


TAB = (box("11/8", [["Atef", "Gabriela", "13", "10", "5", "50%"],
                    ["", "Nicole", "40", "4", "1", "25%"],
                    ["Omar", "Gabriela", "9", "10", "8", "80%"],
                    ["Kash", "Valeria", "", "", "", "#DIV/0!"]])
       + box("11/1", [["Atef", "Gabriela", "1", "4", "1", ""], ["Omar", "Gabriela", "1", "2", "2", ""]])
       + box("10/25", [["Atef", "Nicole", "1", "2", "1", ""]]))


class Weeks(unittest.TestCase):
    def test_parse_reads_by_header_and_fills_owner_down(self):
        w = build.parse_weeks(TAB, TODAY)
        self.assertEqual([x.label for x in w], ["11/8", "11/1", "10/25"])
        self.assertEqual(w[0].start, dt.date(2026, 11, 8))
        self.assertEqual([(r.owner, r.interviewer, r.booked, r.showed) for r in w[0].rows],
                         [("Atef", "Gabriela", 10, 5), ("Atef", "Nicole", 4, 1),
                          ("Omar", "Gabriela", 10, 8), ("Kash", "Valeria", 0, 0)])

    def test_interviewer_sums_across_offices_and_ranks(self):
        pi, po = build.podiums(build.parse_weeks(TAB, TODAY))
        self.assertEqual([(l.name, l.booked, l.showed) for l in pi.lines],
                         [("Gabriela", 20, 13), ("Nicole", 4, 1)])   # Valeria: 0 booked, left out
        self.assertEqual(pi.lines[0].detail, ["Atef", "Omar"])
        self.assertEqual([(l.name, l.booked, l.showed) for l in po.lines],
                         [("Omar", 10, 8), ("Atef", 14, 6)])

    def test_history_is_prior_weeks_oldest_first(self):
        pi, po = build.podiums(build.parse_weeks(TAB, TODAY))
        self.assertEqual(pi.history_labels, ["10/25", "11/1"])
        g = pi.lines[0]
        self.assertEqual(g.history, [None, 0.5])          # 10/25 none, 11/1 = 3/6
        self.assertEqual(pi.lines[1].history, [0.5, None])

    def test_colour_fifty_is_green(self):
        self.assertEqual(build.colour(0.5), "good")
        self.assertEqual(build.colour(0.496), "good")      # shows as 50%
        self.assertEqual(build.colour(0.494), "bad")
        self.assertEqual(build.colour(None), "")

    def test_yesterday_never_invented(self):
        day = dt.date(2026, 11, 10)
        bi, bo, has = build.yesterday_boards({"Atef": {dt.date(2026, 11, 9): SimpleNamespace(by={"G": [3, 2]})}}, day)
        self.assertFalse(has)
        bi, bo, has = build.yesterday_boards(
            {"Atef": {day: SimpleNamespace(by={"G": [3, 2], "N": [2, 0]})},
             "Omar": {day: SimpleNamespace(by={"G": [1, 1]})}}, day)
        self.assertTrue(has)
        self.assertEqual([(l.name, l.booked, l.showed) for l in bi.lines], [("G", 4, 3), ("N", 2, 0)])
        self.assertEqual([(l.name, l.booked, l.showed) for l in bo.lines], [("Omar", 1, 1), ("Atef", 5, 2)])


if __name__ == "__main__":
    unittest.main()
