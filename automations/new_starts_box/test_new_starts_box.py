# -*- coding: utf-8 -*-
"""Offline tests for the Wednesday New Starts fill.

Run:  .venv/Scripts/python -m unittest
          automations.new_starts_box.test_new_starts_box

Every fixture below is a real shape off 'Sales Board WE 9.13' / 'Line Up WE
9.13' / 'D2D OBCL 9.7' on 2026-09-09 -- the spellings that actually broke a
naive match, not invented ones.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.new_starts_box import box as X
from automations.new_starts_box import config as C
from automations.new_starts_box import fill as F
from automations.new_starts_box import sources as S
from automations.new_starts_box.names import keys, match, norm

WED = dt.date(2026, 9, 9)


def grid(rows):
    """Pad a list of row-lists into a rectangle, like get_all_values."""
    w = max((len(r) for r in rows), default=0)
    return [list(r) + [""] * (w - len(r)) for r in rows]


def board(entries, roster=(), team_col=26):
    """A board tab: row 1 labels, a roster, TOTALS, then the New Starts box.

    entries: [(name, trainer, location, team)] for the box.
    roster:  [(name, team)] above TOTALS.
    """
    w = max(team_col, 30)
    row1 = [""] * w
    row1[team_col - 1] = C.ROSTER_TEAM_LABEL
    rows = [row1, [""] * w, [""] * w]
    for name, team in roster:
        r = [""] * w
        r[2], r[team_col - 1] = name, team
        rows.append(r)
    tot = [""] * w
    tot[2] = "TOTALS"
    rows.append(tot)
    title = [""] * w
    title[2] = C.BOX_TITLE
    rows.append(title)
    head = [""] * w
    head[2], head[3] = C.BOX_NAME_LABEL, C.BOX_TRAINER_LABEL
    head[10], head[25] = C.BOX_LOCATION_LABEL, C.BOX_TEAM_LABEL
    rows.append(head)
    rows.append([""] * w)                       # the blank row people leave
    for name, trainer, loc, team in entries:
        r = [""] * w
        r[2], r[3], r[10], r[25] = name, trainer, loc, team
        rows.append(r)
    return grid(rows)


class Norm(unittest.TestCase):
    def test_strips_week_suffix_accents_and_quotes(self):
        self.assertEqual(norm('Terrance "Dior" Dandy'),
                         "terrance dior dandy")
        self.assertEqual(norm("Miguel Rodríguez Tapia"),
                         "miguel rodriguez tapia")
        self.assertEqual(norm("Ana Griffin (Wk 3)"), "ana griffin")
        self.assertEqual(norm("Ja'vanna Nash (Wk 2)"), "ja vanna nash")

    def test_nickname_is_a_lookup_key_but_a_week_marker_is_not(self):
        self.assertEqual(keys("Amjad (MJ) Malhas (Wk 2)"),
                         {"amjad malhas", "mj"})
        self.assertEqual(keys("Safiya Mahmoud (NC)"), {"safiya mahmoud"})


class Match(unittest.TestCase):
    CANDS = [("Sydney Agnew ", "A"), ("Calvin Bates Johnson", "B"),
             ("Amjad (MJ) Malhas (Wk 2)", "C"), ("Chloe Johnson ", "D")]

    def test_exact_wins_and_says_nothing(self):
        self.assertEqual(match("Sydney Agnew", self.CANDS), ("A", ""))

    def test_token_subset_finds_the_pasted_surname(self):
        hit, note = match("Calvin Bates", self.CANDS)
        self.assertEqual(hit, "B")
        self.assertIn("name tokens", note)

    def test_nickname_is_the_last_resort(self):
        hit, note = match("MJ", self.CANDS)
        self.assertEqual(hit, "C")
        self.assertIn("nickname", note)

    def test_two_candidates_is_a_question_not_a_guess(self):
        hit, note = match("Johnson", self.CANDS)
        self.assertIsNone(hit)
        self.assertIn("could be any of", note)

    def test_nobody_is_reported_not_swallowed(self):
        hit, note = match("Nita Castillo", self.CANDS)
        self.assertIsNone(hit)
        self.assertIn("matches nothing", note)


class FindBox(unittest.TestCase):
    def test_finds_the_box_wherever_the_roster_ends(self):
        g = board([("Angelyn Galegos", "", "", "")],
                  roster=[("Alyssa Moreno ", "Se7en Sins")])
        hrow, cols = X.find_box(g)
        self.assertEqual(X.cell(g, hrow, 3), C.BOX_NAME_LABEL)
        self.assertEqual(cols[C.BOX_TRAINER_LABEL], 4)
        self.assertEqual(cols[C.BOX_LOCATION_LABEL], 11)
        self.assertEqual(cols[C.BOX_TEAM_LABEL], 26)
        self.assertEqual([n for _r, n in X.entries(g, hrow)],
                         ["Angelyn Galegos"])

    def test_a_renamed_box_stops_the_run(self):
        g = board([("A", "", "", "")])
        g[len(g) - 3][2] = "New Starts"          # the title, renamed
        with self.assertRaises(RuntimeError):
            X.find_box(g)

    def test_a_missing_column_stops_the_run_and_names_it(self):
        g = board([("A", "", "", "")])
        hrow, _ = X.find_box(g)
        g[hrow - 1][25] = ""                     # drop the Team header
        with self.assertRaises(RuntimeError) as e:
            X.find_box(g)
        self.assertIn(C.BOX_TEAM_LABEL, str(e.exception))


class CollectPairs(unittest.TestCase):
    # 'Is Training' in col 1, new starts in cols 2..4 -- one trainer can take
    # three, and the second and third columns have no header of their own.
    LINEUP = grid([
        ["Is Training", "New Start Name", "", ""],
        ["Sydney Agnew ", "Jayla Callier", "Ashari Evans", ""],
        ["Giovanna Santos", "Tyler Ketchum", "", "Stephanie Aramayo Riveros"],
        ["Willvim Marte ", "", "", "Maurice Smith"],
        ["Lakeiah Gregory", "Ashari Evans", "", ""],
        ["", "", "", ""],
    ])

    def test_reads_every_trainee_column_including_a_gap(self):
        pairs, _notes = S.collect_pairs(self.LINEUP, 1, 1, 2, 4)
        self.assertIn(("Stephanie Aramayo Riveros", "Giovanna Santos"), pairs)
        self.assertIn(("Maurice Smith", "Willvim Marte"), pairs)

    def test_first_mention_wins_and_the_second_is_reported(self):
        pairs, notes = S.collect_pairs(self.LINEUP, 1, 1, 2, 4)
        self.assertEqual([t for n, t in pairs if n == "Ashari Evans"],
                         ["Sydney Agnew"])
        self.assertTrue(any("twice" in n for n in notes))


class Plan(unittest.TestCase):
    ROSTER = [("Alyssa Moreno ", "Se7en Sins"),
              ("Amjad (MJ) Malhas (Wk 2)", "Alphaletes")]
    TRAINERS = [("Angelyn Galegos", "Alyssa Moreno "),
                ("Eriyana White", "MJ"),
                ("Moises Turrubiartes", "BAS")]
    LOCS = [("Angelyn Galegos", "Rockwall"), ("Eriyana White", "Denton")]

    def plan(self, entries, **kw):
        g = board(entries, roster=self.ROSTER)
        return g, F.plan(g, WED, self.TRAINERS, self.LOCS, **kw)

    def test_fills_the_three_columns_of_an_empty_row(self):
        _g, (ups, _notes, counts) = self.plan(
            [("Angelyn Galegos", "", "", "")])
        self.assertEqual({u["range"]: u["values"][0][0] for u in ups},
                         {"D10": "Alyssa Moreno", "K10": "Rockwall",
                          "Z10": "Se7en Sins"})
        self.assertEqual(counts["filled"], 3)

    def test_a_trainers_nickname_still_finds_their_team(self):
        _g, (ups, _n, _c) = self.plan([("Eriyana White", "", "", "")])
        self.assertIn({"range": "Z10", "values": [["Alphaletes"]]}, ups)

    def test_an_off_roster_trainer_falls_back_to_last_weeks_box(self):
        _g, (ups, notes, _c) = self.plan(
            [("Moises Turrubiartes", "", "", "")],
            fallback_teams=[("Bas", "Hashiras")])
        self.assertIn({"range": "Z10", "values": [["Hashiras"]]}, ups)
        self.assertTrue(any("last week" in n for n in notes))

    def test_nothing_known_leaves_the_cells_alone(self):
        _g, (ups, notes, counts) = self.plan([("Nita Castillo", "", "", "")])
        self.assertEqual(ups, [])
        self.assertEqual(counts["blank"], 3)
        self.assertTrue(any("Nita Castillo" in n for n in notes))

    def test_a_hand_typed_value_is_never_replaced_by_default(self):
        _g, (ups, notes, counts) = self.plan(
            [("Angelyn Galegos", "Alyssa Moreno", "Seagonville", "Se7en Sins")])
        self.assertEqual(ups, [])
        self.assertEqual(counts["replaced"], 0)
        self.assertTrue(any("left alone" in n for n in notes))

    def test_overwrite_replaces_it_and_prints_what_it_replaced(self):
        _g, (ups, notes, counts) = self.plan(
            [("Angelyn Galegos", "Alyssa Moreno", "Seagonville", "Se7en Sins")],
            overwrite=True)
        self.assertEqual(ups, [{"range": "K10", "values": [["Rockwall"]]}])
        self.assertEqual(counts["replaced"], 1)
        self.assertTrue(any("'Seagonville' -> 'Rockwall'" in n for n in notes))

    def test_it_never_writes_outside_the_three_columns(self):
        _g, (ups, _n, _c) = self.plan([("Angelyn Galegos", "", "", "")])
        self.assertEqual({u["range"][0] for u in ups}, {"D", "K", "Z"})


class TabTitles(unittest.TestCase):
    def test_wednesday_reads_this_weeks_sunday_and_this_weeks_monday(self):
        self.assertEqual(C.board_tab(WED), "Sales Board WE 9.13")
        self.assertEqual(C.lineup_tab(WED), "Line Up WE 9.13")
        self.assertEqual(C.obcl_tab(WED), "D2D OBCL 9.7")

    def test_a_sunday_run_still_belongs_to_the_week_that_is_ending(self):
        sun = dt.date(2026, 9, 13)
        self.assertEqual(C.board_tab(sun), "Sales Board WE 9.13")
        self.assertEqual(C.obcl_tab(sun), "D2D OBCL 9.7")


if __name__ == "__main__":
    unittest.main()
