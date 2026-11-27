"""Pure tests for boxes.py -- no Google, no browser, nothing sent.

    python -m unittest automations.interviewer_retention.test_boxes
"""
import datetime as dt
import unittest

from automations.interviewer_retention import boxes as bx

SUN = dt.date(2026, 11, 22)          # the box label: the Sunday that ENDS the week
MON, THU, FRI, SAT = (SUN - dt.timedelta(days=k) for k in (6, 3, 2, 1))


def iv(name, d1=None, q="", a="", b="", d2=None, s=""):
    return bx.Interview(name, d1, q, a, b, d2, s)


class Qualified(unittest.TestCase):
    def test_counts_and_percent_per_day(self):
        rows = [iv("Victoria", MON, bx.QUALIFY), iv("Victoria", MON, bx.QUALIFY),
                iv("Victoria", MON, bx.DISQUALIFY), iv("Victoria", MON, bx.DECLINED)]
        mon = bx.qualified_box(rows, SUN)[0]["days"][0]
        self.assertEqual((mon["Q"], mon["Di"], mon["De"]), (2, 1, 1))
        self.assertAlmostEqual(mon["QR"], 0.5)

    def test_saturday_counts_in_total_but_has_no_day_box(self):
        rows = [iv("Ludmila", SAT, bx.QUALIFY)]
        box = bx.qualified_box(rows, SUN)[0]
        self.assertEqual(sum(d["Q"] for d in box["days"]), 0)
        self.assertEqual(box["total"]["Q"], 1)

    def test_a_day_with_nobody_is_zero_not_an_error(self):
        box = bx.qualified_box([iv("Mavi", FRI, bx.QUALIFY)], SUN)[0]
        self.assertEqual(box["days"][0]["QR"], 0.0)

    def test_interviewers_listed_in_first_seen_order(self):
        rows = [iv("B", THU, bx.QUALIFY), iv("A", MON, bx.QUALIFY), iv("B", FRI, bx.QUALIFY)]
        self.assertEqual([r["interviewer"] for r in bx.qualified_box(rows, SUN)], ["B", "A"])


class Answered(unittest.TestCase):
    def test_rates_are_over_qualified(self):
        rows = [iv("V", MON, bx.QUALIFY, bx.ANSWERED, bx.BOOKED),
                iv("V", MON, bx.QUALIFY, bx.NOT_CONTACTED),
                iv("V", MON, bx.QUALIFY, bx.NO_ANSWER),
                iv("V", MON, bx.QUALIFY)]
        mon = bx.answered_box(rows, SUN)[0]["days"][0]
        self.assertEqual((mon["Q"], mon["A"], mon["B"], mon["NC"]), (4, 1, 1, 1))
        self.assertAlmostEqual(mon["AR"], 0.25)
        self.assertAlmostEqual(mon["NCR"], 0.25)


class Second(unittest.TestCase):
    def test_listed_under_first_round_interviewer_by_second_round_date(self):
        rows = [iv("Valentina R", dt.date(2026, 11, 10), bx.QUALIFY, bx.ANSWERED, bx.BOOKED, SAT, bx.SHOWED),
                iv("Valentina R", dt.date(2026, 11, 10), bx.QUALIFY, bx.ANSWERED, bx.BOOKED, SAT, bx.CANCELLED)]
        box = bx.second_box(rows, SUN)[0]
        sat = box["days"][5]
        self.assertEqual((box["interviewer"], sat["B"], sat["S"], sat["C"]), ("Valentina R", 2, 1, 1))
        self.assertEqual(box["total"], {"Booked": 2, "Showed": 1, "R": 0.5})


if __name__ == "__main__":
    unittest.main()
