"""Roster-token matching on the Verizon board (Carlos 2026-11-07/08).

  python -m automations.vantura_slack_sales.test_match_rep
"""
from __future__ import annotations

import unittest

from automations.vantura_slack_sales.run import _norm, match_rep

BOARD = ["Edgar Camunez", "Will Bautista", "Diego Chacon", "Jayden Willingham",
         "Jair Hernandez Otero", "Nicholas Esmerado Macias", "Thais Alvarez Aragon",
         "Gary Van Whitaker", "Isaac Salomon Nambo", "Richard Bautista", "Brandy Ahumada Ruiz",
         "Ja'nevaeh Renee Winkley", "Marco Antonio Hernandez", "Angel Rivera", "Jose Ramos",
         "Shayan Khan Jadooh", "Giovanni Monreal", "Nico Murrugarra", "Jaime Jacob Castillo"]
ROWS = {_norm(n): i for i, n in enumerate(BOARD, start=5)}


class RosterTokens(unittest.TestCase):
    def m(self, token):
        return match_rep(token, ROWS)

    def test_first_or_last_name(self):
        self.assertEqual(self.m("CHACON"), _norm("Diego Chacon"))
        self.assertEqual(self.m("Will"), _norm("Will Bautista"))
        self.assertEqual(self.m("Jair"), _norm("Jair Hernandez Otero"))
        self.assertEqual(self.m("Jair Otero"), _norm("Jair Hernandez Otero"))     # first+last
        self.assertEqual(self.m("ISAAC"), _norm("Isaac Salomon Nambo"))
        self.assertEqual(self.m("THAIS"), _norm("Thais Alvarez Aragon"))

    def test_room_nicknames(self):
        self.assertEqual(self.m("SAMANTHA"), _norm("Brandy Ahumada Ruiz"))
        self.assertEqual(self.m("Samantha Ruiz"), _norm("Brandy Ahumada Ruiz"))
        self.assertEqual(self.m("GIO"), _norm("Giovanni Monreal"))
        self.assertEqual(self.m("Nick"), _norm("Nicholas Esmerado Macias"))
        self.assertEqual(self.m("Bautista"), _norm("Will Bautista"))
        self.assertEqual(self.m("William"), _norm("Will Bautista"))     # 11/10 roster spelling
        self.assertEqual(self.m("Nico"), _norm("Nico Murrugarra"))

    def test_middle_name_go_by(self):
        self.assertEqual(self.m("JACOB"), _norm("Jaime Jacob Castillo"))

    def test_first_name_beats_middle_name(self):
        rows = dict(ROWS)
        rows[_norm("Jacob Ortega")] = 99                 # a FIRST name wins over a middle name
        self.assertEqual(match_rep("JACOB", rows), _norm("Jacob Ortega"))

    def test_never_guesses(self):
        rows = dict(ROWS)
        rows[_norm("Jacob Ortega")] = 99
        rows[_norm("Jacob Diego Raya")] = 100            # two first names -> no match
        self.assertIsNone(match_rep("JACOB", rows))
        rows2 = dict(ROWS)
        rows2[_norm("Ana Jacob Perez")] = 101            # two middle names -> no match
        self.assertIsNone(match_rep("JACOB", rows2))
        self.assertIsNone(self.m("Rudy"))


if __name__ == "__main__":
    unittest.main()
