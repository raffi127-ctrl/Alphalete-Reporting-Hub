"""The team split, offline — no Sheets, no ownerville, no Slack.

What these pin is the part that can go wrong quietly: a rep filed under the
wrong team, a rep dropped because neither spelling matched, and the flat board
changing shape on an office that has no sales board to read.

    python -m unittest automations.weekly_knock_dispositions.test_teams
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automations.total_knocks.pull import (COL_FIRST_KNOCK, COL_LAST_KNOCK,
                                           COL_REP)
from automations.weekly_knock_dispositions import board as B
from automations.weekly_knock_dispositions import teams as T
from automations.weekly_knock_dispositions.pull import (
    K_DAILY_GAP_MIN, K_DAILY_KNOCKS, K_GAP_MIN, K_TALK_TO, K_TOTAL_KNOCKS,
    K_TOTAL_LEADS)


def _book(pairs):
    """A TeamBook built straight from (board name, team) — the same maps
    teams.load() builds, without the Sheets read."""
    return T.TeamBook(
        tab="test",
        teams=T.team_order({t for _n, t in pairs}),
        counts={},
        _exact=T._unique([(T._norm(n), t) for n, t in pairs]),
        _plain=T._unique([(T._plain(n), t) for n, t in pairs]),
        _short=T._unique([(T._short(n), t) for n, t in pairs if T._short(n)]),
    )


def _rep(name, talk=30, knocks=600):
    return {COL_REP: name, K_TALK_TO: talk,
            K_TOTAL_KNOCKS: knocks, K_TOTAL_LEADS: knocks + 10,
            K_DAILY_KNOCKS: [knocks // 6] * 6, K_GAP_MIN: 300,
            K_DAILY_GAP_MIN: [50] * 6,
            COL_FIRST_KNOCK: "11:10 AM", COL_LAST_KNOCK: "7:20 PM"}


BOARD = [("Hank Tran", "Se7en Sins"),
         ("Noemi (Ivette) Ontiveros", "Se7en Sins"),
         ('Terrance "Dior" Dandy', "Ceaseless"),
         ("Ibukunoluwa Olapade Ogunlola", "Alphaletes"),
         ("Andrew Sanborn", "Mindset Engine")]


class TeamLookup(unittest.TestCase):
    def setUp(self):
        self.book = _book(BOARD)

    def test_exact_and_case(self):
        self.assertEqual(self.book.team_for("Hank Tran"), "Se7en Sins")
        self.assertEqual(self.book.team_for("hank tran"), "Se7en Sins")

    def test_nickname_in_the_board_cell(self):
        """OwnerVille spells them plainly; the board carries the nickname."""
        self.assertEqual(self.book.team_for("Noemi Ontiveros"), "Se7en Sins")
        self.assertEqual(self.book.team_for("Terrance Dandy"), "Ceaseless")

    def test_middle_name_on_one_side_only(self):
        self.assertEqual(self.book.team_for("Ibukunoluwa Ogunlola"),
                         "Alphaletes")

    def test_ownerville_status_suffix(self):
        """'Andrew Sanborn Roadtrip' is the board's 'Andrew Sanborn' — the
        same shape board.match_apps already matches for the apps column."""
        self.assertEqual(self.book.team_for("Andrew Sanborn Roadtrip"),
                         "Mindset Engine")

    def test_unknown_rep_is_blank_not_guessed(self):
        self.assertEqual(self.book.team_for("Brand New Person"), "")

    def test_two_reps_one_key_is_dropped_not_guessed(self):
        """A key two reps share tells us nothing about either of them."""
        book = _book([("Chris Lee", "Hashiras"), ("Chris Lee", "Ceaseless")])
        self.assertEqual(book.team_for("Chris Lee"), "")

    def test_apostrophes_are_spellings_not_asides(self):
        book = _book([("Ja'vanna Nash", "Ceaseless")])
        self.assertEqual(book.team_for("Ja'vanna Nash"), "Ceaseless")

    def test_team_order_is_alphabetical_unassigned_last(self):
        self.assertEqual(
            T.team_order(["Se7en Sins", T.UNASSIGNED, "alpha", "Ceaseless"]),
            ["alpha", "Ceaseless", "Se7en Sins", T.UNASSIGNED])


class Grouping(unittest.TestCase):
    def setUp(self):
        self.book = _book(BOARD)
        self.ov = [_rep("Hank Tran"), _rep("Noemi Ontiveros"),
                   _rep("Terrance Dandy"), _rep("Andrew Sanborn Roadtrip"),
                   _rep("Brand New Person")]
        self.apps = {"Hank Tran": 5, "Terrance Dandy": 2, "Sales Only Rep": 4}

    def _rows(self):
        return B.compute_rows_by_team(self.ov, self.apps, [], self.book)

    def test_office_totals_stay_first_and_office_wide(self):
        rows = self._rows()
        self.assertEqual(rows[0][1], B.TOTALS_LABEL)
        flat = B.compute_rows(self.ov, self.apps, [])
        self.assertEqual(rows[0], flat[0])   # the headline number is the same

    def test_one_band_per_team_in_order(self):
        bands = [r[1] for r in self._rows() if B.is_team_row(r)]
        self.assertEqual(bands, [
            f"{B.TEAM_ROW_PREFIX}CEASELESS",
            f"{B.TEAM_ROW_PREFIX}MINDSET ENGINE",
            f"{B.TEAM_ROW_PREFIX}SE7EN SINS",
            f"{B.TEAM_ROW_PREFIX}UNASSIGNED"])

    def test_every_rep_appears_exactly_once(self):
        rows = self._rows()
        names = [r[1] for r in rows[1:] if not B.is_team_row(r)]
        self.assertEqual(sorted(names), sorted(
            [r[1] for r in B.compute_rows(self.ov, self.apps, [])[1:]]))

    def test_sales_only_rep_lands_in_unassigned(self):
        rows = self._rows()
        band = next(i for i, r in enumerate(rows)
                    if r[1] == f"{B.TEAM_ROW_PREFIX}UNASSIGNED")
        under = [r[1] for r in rows[band + 1:]]
        self.assertIn("Sales Only Rep", under)
        self.assertIn("Brand New Person", under)

    def test_apps_follow_the_rep_into_their_team(self):
        """Hank's 5 apps are on Se7en Sins' band, not somebody else's."""
        rows = self._rows()
        apps_col = B.headers_for([]).index("Total Apps")
        band = next(r for r in rows
                    if r[1] == f"{B.TEAM_ROW_PREFIX}SE7EN SINS")
        self.assertEqual(band[apps_col], "5")

    def test_row_width_matches_the_flat_board(self):
        flat = len(B.compute_rows(self.ov, self.apps, [])[0])
        self.assertTrue(all(len(r) == flat for r in self._rows()))


class Numbering(unittest.TestCase):
    """number_rows renumbers in place — the count beside a rep is their place
    in their OWN team, and a band keeps the 'K of N' totals_row gave it."""

    def test_numbering_restarts_under_each_band(self):
        book = _book(BOARD)
        ov = [_rep("Hank Tran"), _rep("Noemi Ontiveros"),
              _rep("Terrance Dandy"), _rep("Andrew Sanborn Roadtrip")]
        rows = B.compute_rows_by_team(ov, None, [], book)
        bands = B.number_rows(rows, 1)          # 1 = OFFICE TOTALS on top

        self.assertEqual(sorted(bands), [i for i, r in enumerate(rows)
                                         if B.is_team_row(r)])
        self.assertNotIn(0, bands)              # OFFICE TOTALS is not a band

        seen, expect, n = [], [], 0
        for i, r in enumerate(rows[1:], start=1):
            if B.is_team_row(r):
                n = 0
                self.assertNotEqual(r[0], "")   # the band keeps its count
                continue
            n += 1
            seen.append(r[0])
            expect.append(str(n))
        self.assertEqual(seen, expect)
        # Se7en Sins has two (Hank + Noemi); the other three teams one each.
        self.assertEqual(seen, ["1", "1", "1", "2"])

    def test_flat_board_still_numbers_straight_through(self):
        ov = [_rep("Hank Tran"), _rep("Noemi Ontiveros"),
              _rep("Terrance Dandy")]
        rows = B.compute_rows(ov, None, [])
        self.assertEqual(B.number_rows(rows, 1), {})
        self.assertEqual([r[0] for r in rows[1:]], ["1", "2", "3"])

    def test_comparison_rows_on_top_do_not_get_numbered(self):
        """run.py inserts another office's totals ABOVE — n_top covers them."""
        ov = [_rep("Hank Tran"), _rep("Terrance Dandy")]
        rows = B.compute_rows_by_team(ov, None, [], _book(BOARD))
        rows[0:0] = [B.totals_row(ov, None, [], label="CHAN PARK TOTALS")]
        B.number_rows(rows, 2)
        self.assertEqual(rows[0][1], "CHAN PARK TOTALS")
        self.assertEqual(rows[1][1], B.TOTALS_LABEL)
        self.assertEqual([r[0] for r in rows[2:] if not B.is_team_row(r)],
                         ["1", "1"])


class Headers(unittest.TestCase):
    """Raf 2026-09-13: the column headers repeat above each team."""

    def _rows(self):
        book = _book(BOARD)
        ov = [_rep("Hank Tran"), _rep("Noemi Ontiveros"),
              _rep("Terrance Dandy"), _rep("Andrew Sanborn Roadtrip")]
        return B.compute_rows_by_team(ov, None, [], book)

    def test_a_band_above_every_team_including_the_first(self):
        rows = self._rows()
        bands = B.number_rows(rows, 1)
        # Ceaseless, Mindset Engine, Se7en Sins — the teams these four reps
        # are actually on. A team with nobody knocking draws no block.
        self.assertEqual(len(bands), 3)
        self.assertEqual(set(bands), {i for i, r in enumerate(rows)
                                      if B.is_team_row(r)})

    def test_the_image_grows_by_one_header_band_per_team(self):
        """The bands are really drawn — not just asked for."""
        from PIL import Image

        from automations.total_knocks import render as R
        hdr, body = ["#", "Rep", "Talk"], [["1", "A", "2"], ["2", "B", "3"],
                                           ["3", "C", "4"], ["4", "D", "5"]]
        with tempfile.TemporaryDirectory() as d:
            flat = R._draw(hdr, body, "t", B.THEME_PLUM,
                           Path(d) / "flat.png", name_col=1)
            band = R._draw(hdr, body, "t", B.THEME_PLUM,
                           Path(d) / "band.png", name_col=1,
                           header_before={1, 3})
            h0 = Image.open(flat).height
            h1 = Image.open(band).height
        self.assertEqual((h1 - h0) % 2, 0)              # two equal bands
        self.assertGreater(h1, h0)

    def test_chan_row_on_top_keeps_its_own_shape(self):
        """The comparison office's totals are NOT a team band — no header
        band above them, and they stay out of the team numbering."""
        rows = self._rows()
        rows[0:0] = [B.totals_row([_rep("Chan Rep")], None, [],
                                  label="CHAN PARK TOTALS")]
        bands = B.number_rows(rows, 2)
        self.assertNotIn(0, bands)                      # Chan
        self.assertNotIn(1, bands)                      # OFFICE TOTALS
        self.assertTrue(all(B.is_team_row(rows[i]) for i in bands))


class NoBoard(unittest.TestCase):
    def test_office_without_a_sales_board_gets_none(self):
        """No entry in SALES_BOARDS = no Sheets call at all, flat board."""
        self.assertIsNone(T.load("Nobody With A Board",
                                 __import__("datetime").date(2026, 9, 12),
                                 verbose=False))


if __name__ == "__main__":
    unittest.main()
