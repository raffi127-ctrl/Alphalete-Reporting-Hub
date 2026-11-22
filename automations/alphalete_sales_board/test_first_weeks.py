"""Friday 1st weeks: New Starts box -> top of the board (Eve 2026-11-22)."""
from __future__ import annotations

import datetime as dt
import re
import unittest

from automations.alphalete_sales_board import first_weeks as FW
from automations.apex_new_starts import board as AB

TODAY = dt.date(2026, 11, 20)


def _cand(name, trainer="", team="", roll=None):
    return AB.Candidate(name=name, trainer=trainer, email="", location="",
                        team=team, reason_lost="",
                        roll=roll or {0: "CR", 1: "Here", 2: "Here"},
                        tab="Sales Board WE 11.22", row=0,
                        week_start=dt.date(2026, 11, 16))


# Row 1 holds the labels (row 3 says REP over several columns -- never used).
R1 = ["", "", "", "MON", "Trainer", "Field Status", "Campaign", "Team",
      "Leadership Status", "Start Date", "Location", "Email"]


def _row(name="", trainer="", status="", camp="", team=""):
    return ["", "", name, "", trainer, status, camp, team, "", "", "", ""]


def _grid(reps, blanks=3):
    g = [R1, [""] * 12, ["", "", "WE", "Apps"] + [""] * 8]
    g += [_row(*r) for r in reps] + [_row() for _ in range(blanks)]
    g += [["", "", "TOTALS"] + [""] * 9]
    return g


class FakeWS:
    def __init__(self, grid):
        self.grid = [list(r) for r in grid]
        self.title = "Sales Board WE 11.22"

    def _set(self, a1, v):
        m = re.match(r"([A-Z]+)(\d+)", a1)
        col = 0
        for ch in m.group(1):
            col = col * 26 + ord(ch) - 64
        r = int(m.group(2))
        row = self.grid[r - 1]
        row += [""] * (col - len(row))
        row[col - 1] = v

    def update_acell(self, a1, v):
        self._set(a1, v)

    def batch_update(self, ups, value_input_option=None):
        for u in ups:
            self._set(u["range"], u["values"][0][0])

    def get_all_values(self):
        return [list(r) for r in self.grid]


ROSTER = [("Pranish Shrestha", "", "Entry Level", "ATT", "Hashiras"),
          ("Willie Henderson", "", "", "ATT", "Ceaseless"),
          ("Kaniyah Moore", "Jay Turnage", "1st Wk", "Spectrum", "Alphaletes")]


class TestPlan(unittest.TestCase):
    def test_adds_missing_with_everything_filled(self):
        g = _grid(ROSTER)
        p = FW.plan(g, [_cand("Jovani Martinez", "Pranish")])
        self.assertEqual(len(p["add"]), 1)
        vals = p["add"][0][1]
        self.assertEqual(vals["Trainer"], "Pranish Shrestha")
        self.assertEqual(vals["Team"], "Hashiras")          # trainer's team
        self.assertEqual(vals["Campaign"], "ATT")
        self.assertEqual(vals["Field Status"], "1st Wk")
        self.assertEqual(vals["Leadership Status"], "In Training")
        self.assertEqual(vals["Start Date"], "11/16/2026")

    def test_terminated_never_goes_up(self):
        g = _grid(ROSTER)
        p = FW.plan(g, [_cand("Toni Gabaldon", "Willie", roll={0: "CR", 3: "Terminated"})])
        self.assertEqual(p["add"], [])
        self.assertTrue(p["skipped"])

    def test_blank_days_after_terminated_still_terminated(self):
        g = _grid(ROSTER)
        p = FW.plan(g, [_cand("Toni Gabaldon", "Willie",
                              roll={0: "CR", 1: "Here", 2: "Terminated", 3: "", 4: ""})])
        self.assertEqual(p["add"], [])
        self.assertEqual(p["doubt"], [])
        self.assertTrue(p["skipped"])

    def test_roll_call_after_terminated_asks_eve(self):
        g = _grid(ROSTER)
        p = FW.plan(g, [_cand("Toni Gabaldon", "Willie",
                              roll={0: "CR", 2: "Terminated", 3: "Here"})])
        self.assertEqual(p["add"], [])
        self.assertEqual(p["skipped"], [])
        self.assertIn("'Here' on Thursday", p["doubt"][0])

    def test_already_on_board_only_fills_empty_cells(self):
        g = _grid(ROSTER + [("Carmen Lopez", "", "1st Wk", "ATT", "Ceaseless")])
        p = FW.plan(g, [_cand("Carmen Lopez", "Willie Henderson")])
        self.assertEqual(p["add"], [])
        (_c, _row_n, cells), = p["complete"]
        self.assertEqual(list(cells.values())[0], "Willie Henderson")
        self.assertNotIn("1st Wk", cells.values())           # typed value kept

    def test_nickname_in_box_matches_board(self):
        g = _grid(ROSTER + [("Alexis Justice", "Bas El Hassan", "1st Wk", "ATT", "Hashiras")])
        p = FW.plan(g, [_cand("Alexis (Lexi) Justice", "Bas")])
        self.assertEqual(p["add"], [])

    def test_shared_surname_is_a_different_person(self):
        g = _grid(ROSTER)
        p = FW.plan(g, [_cand("Ailonnie Moore", "Willie")])
        self.assertEqual(len(p["add"]), 1)

    def test_near_spelling_is_held_for_a_person(self):
        g = _grid(ROSTER + [("Jovanni Martinez", "", "1st Wk", "", "")])
        p = FW.plan(g, [_cand("Jovani Martinez", "Pranish")])
        self.assertEqual(p["add"], [])
        self.assertTrue(any("could be" in d for d in p["doubt"]))

    def test_short_trainer_read_from_board_trainer_column(self):
        g = _grid(ROSTER + [("Gerardo Marquez", "Bas El Hassan", "2nd Wk", "ATT", "Hashiras")])
        p = FW.plan(g, [_cand("Priscilla Hernandez Ibarra", "Bas", team="Hashiras")])
        self.assertEqual(p["add"][0][1]["Trainer"], "Bas El Hassan")


class TestApply(unittest.TestCase):
    def test_writes_name_and_details_into_a_blank_row(self):
        ws = FakeWS(_grid(ROSTER))
        g = ws.get_all_values()
        p = FW.plan(g, [_cand("Jovani Martinez", "Pranish")])
        notes = FW.apply(ws, g, p)
        self.assertEqual(notes, [])
        row = next(r for r in ws.grid if r[2] == "Jovani Martinez")
        self.assertEqual(row[4], "Pranish Shrestha")
        self.assertEqual(row[5], "1st Wk")
        self.assertEqual(row[7], "Hashiras")

    def test_no_blank_rows_says_so(self):
        ws = FakeWS(_grid(ROSTER, blanks=0))
        g = ws.get_all_values()
        p = FW.plan(g, [_cand("Jovani Martinez", "Pranish")])
        notes = FW.apply(ws, g, p)
        self.assertTrue(notes and "NOT added" in notes[0])


if __name__ == "__main__":
    unittest.main()
