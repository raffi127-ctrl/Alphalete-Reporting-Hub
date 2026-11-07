"""Verizon board fill from Credico — plan() against the live 11/7 board shape.

  python -m automations.vantura_verizon_credico.test_run
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.verizon_office.parse import RepWeek, SalesVerification, Week
from automations.vantura_verizon_credico import run as R

TODAY = dt.date(2026, 11, 7)            # Saturday; board shows WE 11.8 (Mon 11/2..Sun 11/8)
HDR = ["#", "REP", "Current Week", "Last Wk", "Monday", "Tuesday", "Wednesday", "Thursday",
       "Friday", "Saturday", "Sunday", "Campaign", "Trainer", "Field Status", "Team",
       "Leadership Status"]


def _rep(n, name, days, extra=()):
    return [str(n), name, "", ""] + list(days) + ["Verizon", "", "", "", ""] + list(extra)


def grid(q_header="", q_vals=()):
    rows = [
        ["", "", "Verizon Sales Board"],
        ["WE", "11.8", "Week Ending 11.8"],
        ["", "", "This Wk", "Last Wk", "MON (2)", "TUE (3)"],
        HDR + ([q_header] if q_header else []),
        _rep(1, "Will Bautista", ["3", "3", "1", "2", "1", "", ""]),
        _rep(2, "Jair Ortero", ["0", "6", "5", "1", "0", "", ""]),
        _rep(3, "Nicholas Esmerado Macias", ["0", "1", "1", "0", "0", "", ""]),
        _rep(4, "Brandy Samantha Ahumada Ruiz", ["0", "0", "0", "0", "0", "", ""]),
        _rep(5, "Angel Rivera", ["X", "X", "X", "X", "X", "", ""]),
        _rep(6, "Nico Murrugarra", ["F", "F", "F", "1", "1", "", ""]),
        _rep(7, "Richard Bautista", ["0", "0", "0", "0", "0", "", ""]),
        ["", "Verizon", "3", "", "3", "10", "7", "4", "2", "0", "0"],
        ["", "Last Week", "", "WE 11.1", "5", "7", "22", "18", "15", "13", "5"],
    ]
    for r, v in q_vals:
        row = rows[r - 1]
        row += [""] * (17 - len(row))
        row[16] = v
    return rows


def week(end, reps):
    return Week(end=end, reps=[RepWeek(name=n, sso="s", days=d, lines=sum(d.values()),
                                       sales=0, vals={"Appr. %": a}) for n, d, a in reps])


def days(sun=0, mon=0, tue=0, wed=0, thu=0, fri=0, sat=0):
    return {"Sun": sun, "Mon": mon, "Tue": tue, "Wed": wed, "Thu": thu, "Fri": fri, "Sat": sat}


def sv(weeks, through=dt.date(2026, 11, 6), overview=None):
    return SalesVerification(path=None, through=through, office="HVA", weeks=weeks,
                             overview=overview or [], references={})


class Names(unittest.TestCase):
    BOARD = ["Will Bautista", "Richard Bautista", "Jair Ortero", "Nicholas Esmerado Macias",
             "Brandy Samantha Ahumada Ruiz", "Nico Murrugarra", "Angel Rivera",
             "Ja'nevaeh Renee Winkley"]

    def test_aliases_and_shapes(self):
        m = lambda n: R.match_rep(n, self.BOARD)[0]
        self.assertEqual(m("William Bautista"), "Will Bautista")
        self.assertEqual(m("Richard Bautista"), "Richard Bautista")
        self.assertEqual(m("Jair Otero"), "Jair Ortero")                 # fuzzy last name
        self.assertEqual(m("Nicholas Macias"), "Nicholas Esmerado Macias")
        self.assertEqual(m("Nicolas Murrugarra"), "Nico Murrugarra")
        self.assertEqual(m("Samantha Ruiz"), "Brandy Samantha Ahumada Ruiz")   # middle name
        self.assertEqual(m("Brandy Ahumada Ruiz"), "Brandy Samantha Ahumada Ruiz")
        self.assertEqual(m("Janevaeh Winkley"), "Ja'nevaeh Renee Winkley")
        self.assertEqual(m("Bautista, William"), "Will Bautista")

    def test_never_guesses(self):
        self.assertEqual(R.match_rep("Giovanni Monreal", self.BOARD), (None, ""))
        self.assertEqual(R.match_rep("Bautista", self.BOARD), (None, ""))      # two Bautistas
        self.assertEqual(R.match_rep("", self.BOARD), (None, ""))


class ShownWeek(unittest.TestCase):
    def test_we_cell(self):
        mon, sun, txt = R.shown_week(grid(), TODAY)
        self.assertEqual((mon, sun, txt), (dt.date(2026, 11, 2), dt.date(2026, 11, 8), "11.8"))

    def test_dropped_zero(self):
        g = grid(); g[1][1] = "8.3"
        mon, sun, _ = R.shown_week(g, dt.date(2026, 8, 28))
        self.assertEqual(sun, dt.date(2026, 8, 30))

    def test_unreadable(self):
        g = grid(); g[1][1] = "pick"
        self.assertEqual(R.shown_week(g, TODAY)[0], None)
        items, problems = R.plan(g, sv([]), TODAY, log=lambda *_: None)
        self.assertEqual(items, [])
        self.assertIn("week cell", problems[0])


class Plan(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.log = self.logs.append

    def _plan(self, g, s):
        items, problems = R.plan(g, s, TODAY, log=self.log)
        return {a1: (old, new, note) for _l, a1, old, new, note in items}, problems

    def test_day_cells_authoritative_inside_covered_days(self):
        s = sv([week(dt.date(2026, 11, 7), [
            ("William Bautista", days(mon=3, tue=2, wed=1, thu=2, fri=1, sat=4), 0.5),
            ("Jair Otero", days(mon=1, tue=6, wed=5, thu=1, fri=0), 0.75),
            ("Nicolas Murrugarra", days(mon=0, tue=0, wed=2, thu=1, fri=1), 1.0),
            ("Angel Rivera", days(), 0),
        ])], overview=[{"Week End Date": dt.date(2026, 11, 7), "% Appr.": 0.6}])
        got, problems = self._plan(grid(), s)
        self.assertEqual(problems, [])
        self.assertEqual(got["F5"][:2], ("3", "2"))                 # lowered Tue
        self.assertIn("LOWERED", got["F5"][2])
        self.assertNotIn("J5", got)                                 # Sat 11/7 > through 11/6
        self.assertEqual(got["E6"][:2], ("0", "1"))                 # raised Mon
        self.assertEqual(got["G10"][:2], ("F", "2"))                # marker replaced by lines
        self.assertNotIn("E10", got)                                # marker kept when 0
        self.assertNotIn("E9", got)                                 # X kept, Credico 0
        self.assertNotIn("E11", got)                                # Richard not in Credico: left alone
        # Approved column
        self.assertEqual(got["Q4"][1], "Approved")
        self.assertEqual(got["Q5"][1], "50%")
        self.assertEqual(got["Q6"][1], "75%")
        self.assertEqual(got["Q10"][1], "100%")
        self.assertEqual(got["Q9"][1], "0%")
        self.assertEqual(got["Q12"][1], "60%")                      # crew row
        self.assertNotIn("Q11", got)                                # blank stays blank
        self.assertTrue(any("Jair Otero -> Jair Ortero" in l for l in self.logs))
        self.assertTrue(any("Richard Bautista" in l and "left alone" in l for l in self.logs))

    def test_blank_stays_blank_and_zero_stays_zero(self):
        s = sv([week(dt.date(2026, 11, 7), [("Richard Bautista", days(), 0)])])
        got, _ = self._plan(grid(), s)
        self.assertEqual([k for k in got if not k.startswith("Q")], [])

    def test_unmatched_reported_not_written(self):
        s = sv([week(dt.date(2026, 11, 7), [("Giovanni Monreal", days(mon=4), 0.5)])])
        got, problems = self._plan(grid(), s)
        self.assertEqual([k for k in got if not k.startswith("Q")], [])
        self.assertTrue(any("Giovanni Monreal" in p for p in problems))

    def test_q_not_free(self):
        g = grid(q_header="Notes")
        s = sv([week(dt.date(2026, 11, 7), [("Richard Bautista", days(mon=1), 0.5)])])
        got, problems = self._plan(g, s)
        self.assertEqual(got["E11"][1], "1")
        self.assertFalse([k for k in got if k.startswith("Q")])
        self.assertTrue(any("not free" in p for p in problems))

    def test_existing_header_and_same_values_not_rewritten(self):
        g = grid(q_header="Approved", q_vals=[(11, "50%"), (12, "60%")])
        s = sv([week(dt.date(2026, 11, 7), [("Richard Bautista", days(), 0.5)])],
               overview=[{"Week End Date": dt.date(2026, 11, 7), "% Appr.": 0.6}])
        got, _ = self._plan(g, s)
        self.assertEqual(got, {})

    def test_stale_approved_cleared(self):
        # rep had a % last week but is not in this week's Credico block
        g = grid(q_header="Approved", q_vals=[(5, "40%")])
        s = sv([week(dt.date(2026, 11, 7), [("Richard Bautista", days(), 0.5)])])
        got, _ = self._plan(g, s)
        self.assertEqual(got["Q5"][1], "(clear)")

    def test_new_board_week_without_credico_block_clears_approved(self):
        g = grid(q_header="Approved", q_vals=[(5, "40%"), (12, "55%")])
        g[1][1] = "11.15"
        s = sv([week(dt.date(2026, 11, 7), [("William Bautista", days(sat=2), 0.5)])],
               through=dt.date(2026, 11, 8))
        items, _ = R.plan(g, s, dt.date(2026, 11, 9), log=self.log)
        got = {a1: new for _l, a1, _o, new, _n in items}
        self.assertEqual(got, {"Q5": "(clear)", "Q12": "(clear)"})   # Sat 11/7 is last week: no day writes

    def test_sunday_of_previous_credico_week_lands_in_board_week(self):
        # Credico WE Sat 11/7 holds Sun 11/1 (board's last week, skipped); Credico WE Sat 11/14
        # holds Sun 11/8 which IS in the board's week -> written when covered.
        s = sv([week(dt.date(2026, 11, 14), [("William Bautista", days(sun=2), 0.5)]),
                week(dt.date(2026, 11, 7), [("William Bautista", days(sun=9, mon=3, tue=3, wed=1, thu=2, fri=1), 0.5)])],
               through=dt.date(2026, 11, 8))
        got, _ = self._plan(grid(), s)
        self.assertEqual(got["K5"][1], "2")
        self.assertEqual([k for k in got if not k.startswith("Q")], ["K5"])


class Apply(unittest.TestCase):
    def test_clear_writes_empty(self):
        class WS:
            def batch_update(self, data, value_input_option=None):
                self.data = data
        ws = WS()
        n = R.apply(ws, [("x", "Q5", "40%", "(clear)", ""), ("y", "E5", "1", "2", "")])
        self.assertEqual(n, 2)
        self.assertEqual(ws.data[0]["values"], [[""]])
        self.assertEqual(ws.data[1]["values"], [["2"]])


if __name__ == "__main__":
    unittest.main()
