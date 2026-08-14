"""Tests for the two rules Eve set on 2026-08-14.

    1. The tab reads alphabetically on BOTH levels — first name, then last —
       and every run leaves it that way, whatever it found.
    2. An apostrophe closes up. "La'mya" is the same person as "Lamya", in
       every direction: the tab, the board, the terminations and OwnerVille.

    python -m unittest automations.mobrium_list.test_order -v
"""
from __future__ import annotations

import unittest

from automations.mobrium_list import sheet as msheet
from automations.mobrium_list.ownerville import Directory, Rep, norm_name


def entry(row, first, last, email="", phone=""):
    return msheet.Entry(row=row, first=first, last=last, email=email, phone=phone)


class FakeWs:
    """Records the one range write `sort_rows` makes."""

    def __init__(self):
        self.writes = []

    def update(self, rng, values, **_kw):
        self.writes.append((rng, values))


class SortOrder(unittest.TestCase):

    def test_last_name_breaks_a_first_name_tie(self):
        rows = [entry(2, "Jennifer", "Nzekwe"), entry(3, "Jennifer", "Medina")]
        self.assertFalse(msheet.is_sorted(rows))
        self.assertEqual([e.last for e in sorted(rows, key=lambda e: e.sort_key)],
                         ["Medina", "Nzekwe"])

    def test_sort_rows_rewrites_one_block_without_losing_anyone(self):
        rows = [entry(2, "Zoria", "Johnson", "z@x.com", "1"),
                entry(3, "Anthony", "Vargas", "a@x.com", "2"),
                entry(4, "Anthony", "Adams", "aa@x.com", "3")]
        ws = FakeWs()
        moved = msheet.sort_rows(ws, rows, dry_run=False, logfn=lambda _m: None)
        # Two of the three change row; Anthony Vargas stays in the middle.
        self.assertEqual(moved, 2)
        (rng, values), = ws.writes
        self.assertEqual(rng, "A2:D4")
        self.assertEqual([v[:2] for v in values],
                         [["Anthony", "Adams"], ["Anthony", "Vargas"],
                          ["Zoria", "Johnson"]])
        # Each person's own email and phone travel with them, untouched.
        self.assertEqual([v[2:] for v in values],
                         [["aa@x.com", "3"], ["a@x.com", "2"], ["z@x.com", "1"]])

    def test_a_sorted_tab_is_not_rewritten(self):
        rows = [entry(2, "Ana", "Ruiz"), entry(3, "Beto", "Sosa")]
        ws = FakeWs()
        self.assertEqual(
            msheet.sort_rows(ws, rows, dry_run=False, logfn=lambda _m: None), 0)
        self.assertEqual(ws.writes, [])

    def test_dry_run_touches_nothing(self):
        rows = [entry(2, "Zoria", "Johnson"), entry(3, "Ana", "Ruiz")]
        ws = FakeWs()
        self.assertEqual(
            msheet.sort_rows(ws, rows, dry_run=True, logfn=lambda _m: None), 2)
        self.assertEqual(ws.writes, [])

    def test_insert_position_places_on_both_levels(self):
        rows = [entry(2, "Anthony", "Adams"), entry(3, "Anthony", "Vargas"),
                entry(4, "Zoria", "Johnson")]
        self.assertEqual(msheet.insert_position(rows, "Anthony", "Molano"), 3)
        self.assertEqual(msheet.insert_position(rows, "Anthony", "Zeta"), 4)
        self.assertEqual(msheet.insert_position(rows, "Aaron", "Diaz"), 2)
        self.assertEqual(msheet.insert_position(rows, "Zoria", "Zeta"), 5)


class Apostrophes(unittest.TestCase):

    def test_apostrophe_closes_up_instead_of_splitting(self):
        self.assertEqual(norm_name("La'mya Joseph"), "lamya joseph")
        self.assertEqual(norm_name("La’mya Joseph"), norm_name("Lamya Joseph"))

    def test_ownerville_finds_her_either_spelling(self):
        d = Directory([Rep(first="La'mya", last="Joseph",
                           email="lamyajoseph17@gmail.com",
                           phone="(469) 928-4000", start="", retired="",
                           roster="active")])
        for spelling in ("Lamya Joseph", "La'mya Joseph", "La’mya Joseph"):
            rep = d.find(spelling)
            self.assertIsNotNone(rep, spelling)
            self.assertEqual(rep.email, "lamyajoseph17@gmail.com")

    def test_a_name_spaced_differently_still_matches(self):
        """Closing the apostrophe must not cost us "O'Neal" == "O Neal"."""
        d = Directory([Rep(first="Shaq", last="O'Neal", email="s@x.com",
                           phone="", start="", retired="", roster="active")])
        self.assertIsNotNone(d.find("Shaq O Neal"))

    def test_two_different_people_still_resolve_to_nobody(self):
        d = Directory([Rep(first="Chris", last="Adams", email="", phone="",
                           start="", retired="", roster="active"),
                       Rep(first="Chris", last="Boone", email="", phone="",
                           start="", retired="", roster="active")])
        self.assertIsNone(d.find("Chris"))


if __name__ == "__main__":
    unittest.main()
