"""Right-hand rep columns never blank (Eve 2026-11-22): details.py + city_check Email/DD."""
from __future__ import annotations

import unittest

from automations.sales_board_fixer import city_check as CC
from automations.sales_board_fixer import details as DT

# Row 1: day banner (so is_board sees a board) + the detail labels.
R1 = ["", "", "", "MON", "", "", "TUES", "Trainer", "Field Status", "Team",
      "Leadership Status", "Email", "Direct Deposit", "Location"]
R3 = ["", "", "WE", "Apps", "Int", "Roll Call", "Apps", "REP", "", "", "", "", "", ""]


def _row(name, trainer="", status="", team="", lead="", email="", dd=""):
    return ["", "", name, "", "", "", "", trainer, status, team, lead, email, dd, ""]


def _grid(rows):
    return [R1, [""] * 14, R3] + rows + [["", "", "TOTALS"] + [""] * 11]


def _fix(found):
    return {(x.name, x.where[:2] if x.where[1].isalpha() else x.where[:1]): x.after
            for x in found if x.fixable}


class TestDetails(unittest.TestCase):
    def test_trainer_and_team_from_last_week(self):
        old = _grid([_row("David Flores", "Justin Carlos Avila", "1st Wk", "Se7en Sins", "In Training")])
        new = _grid([_row("David Flores (Wk 2)", "", "2nd Wk", "", "In Training")])
        found = DT.check("WE", new, old)
        got = {x.after for x in found if x.fixable}
        self.assertEqual(got, {"Justin Carlos Avila", "Se7en Sins"})

    def test_team_from_trainer_when_no_last_week(self):
        new = _grid([_row("Willie Henderson", "", "5th wk+", "Ceaseless", "Leader"),
                     _row("Carmen Lopez", "Willie Henderson", "1st Wk", "", "In Training")])
        found = DT.check("WE", new, None)
        self.assertEqual([x.after for x in found if x.fixable], ["Ceaseless"])

    def test_veteran_without_trainer_is_fine(self):
        new = _grid([_row("Basil Elhassan", "", "5th wk+", "Hashiras", "Mastermind")])
        self.assertEqual(DT.check("WE", new, None), [])

    def test_new_rep_without_any_trainer_is_listed_not_guessed(self):
        new = _grid([_row("Nobody Known", "", "1st Wk", "Hashiras", "In Training")])
        found = DT.check("WE", new, None)
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].fixable)

    def test_blank_field_status_is_listed(self):
        new = _grid([_row("Ana Griffin", "Travis Smith", "", "Alphaletes", "Leader")])
        found = DT.check("WE", new, None)
        self.assertEqual([x.fixable for x in found], [False])

    def test_typed_values_never_touched(self):
        old = _grid([_row("Ana Griffin", "Someone Else", "2nd Wk", "Other", "Leader")])
        new = _grid([_row("Ana Griffin", "Travis Smith", "3rd Wk", "Alphaletes", "Leader")])
        self.assertEqual(DT.check("WE", new, old), [])

    def test_excluded_manager_skipped(self):
        new = _grid([_row("Joshua Mascorro", "", "1st Wk", "", "")])
        self.assertEqual(DT.check("WE", new, None), [])


class TestEmailDD(unittest.TestCase):
    def test_blank_email_and_dd_filled_from_signed_packet(self):
        g = _grid([_row("Austin Eubanks", "AL", "1st Wk", "Se7en Sins", "In Training")])
        rows = [(4, "Austin Eubanks", "")]
        info = {"Austin Eubanks": {"city": "Plano", "why": "", "email": "a@x.com", "signed": True}}
        got = {w: v for _r, _n, _c, v, w in CC.plan_extra(g, rows, info)}
        self.assertEqual(got, {"Email": "a@x.com"})      # DD is OFF (Eve 11/22)

    def test_typed_dd_and_no_packet_left_alone(self):
        g = _grid([_row("Roxxanne Rose", dd="Can't get DD"), _row("No Packet")])
        rows = [(4, "Roxxanne Rose", ""), (5, "No Packet", "")]
        info = {"Roxxanne Rose": {"city": "", "why": "", "email": "", "signed": True},
                "No Packet": {"city": "", "why": "no signed Blue Ink packet"}}
        self.assertEqual(CC.plan_extra(g, rows, info), [])


if __name__ == "__main__":
    unittest.main()
