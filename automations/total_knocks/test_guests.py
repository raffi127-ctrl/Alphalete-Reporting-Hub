"""The guest-rep split: who comes off the host's board, and who never does.

    .venv/bin/python -m unittest automations.total_knocks.test_guests
"""
from __future__ import annotations

import unittest

from automations.total_knocks import guests as G

HOST = "Rafael Hidalgo"
GUEST = "Carlos Hidalgo"


def rows(*names):
    return [{"Rep": n, "Total Knocks": 10} for n in names]


def reps(rs):
    return [r["Rep"] for r in rs]


class RosterTests(unittest.TestCase):
    def test_carlos_is_raf_s_guest(self):
        self.assertEqual(G.guests_of(HOST), [GUEST])
        self.assertTrue(G.has_guests(HOST))
        self.assertEqual(len(G.roster(HOST, GUEST)), 14)

    def test_an_office_with_no_guests_pays_nothing(self):
        self.assertFalse(G.has_guests("Chan Park"))
        rs = rows("Somebody Else")
        host, guest = G.split("Chan Park", rs)
        self.assertEqual(host, rs)
        self.assertEqual(guest, {})


class MatchingTests(unittest.TestCase):
    def test_exact_spelling(self):
        host, guest = G.split(HOST, rows("Christian Perez", "Hank Tran"))
        self.assertEqual(reps(host), ["Hank Tran"])
        self.assertEqual(reps(guest[GUEST]), ["Christian Perez"])

    def test_ownerville_middle_name(self):
        # Carlos typed 'Jose Pimentel Lugo'; the grid says 'Jose Manuel …'.
        host, guest = G.split(HOST, rows("Jose Manuel Pimentel Lugo"))
        self.assertEqual(host, [])
        self.assertEqual(reps(guest[GUEST]), ["Jose Manuel Pimentel Lugo"])

    def test_status_word_in_the_name_cell(self):
        host, guest = G.split(HOST, rows("Yariel Nieto Caban Roadtrip"))
        self.assertEqual(host, [])
        self.assertEqual(len(guest[GUEST]), 1)

    def test_every_rostered_rep_is_reachable(self):
        # The roster as typed: all fourteen must come off the board, or the
        # names in GUEST_REPS have drifted from ownerville's spelling.
        host, guest = G.split(HOST, rows(*G.roster(HOST, GUEST)))
        self.assertEqual(host, [])
        self.assertEqual(len(guest[GUEST]), 14)

    def test_two_de_la_torres_stay_apart(self):
        host, guest = G.split(HOST, rows("Aaron De La Torre",
                                         "Andrew De La Torre"))
        self.assertEqual(host, [])
        self.assertEqual(sorted(reps(guest[GUEST])),
                         ["Aaron De La Torre", "Andrew De La Torre"])

    def test_a_namesake_is_left_on_the_host_board(self):
        # Two rows read as one roster name. Neither moves: a rep left on
        # Raf's board gets corrected out loud, a rep moved by a guess doesn't.
        host, guest = G.split(HOST, rows("Christian Andres Perez",
                                         "Christian Miguel Perez"))
        self.assertEqual(len(host), 2)
        self.assertEqual(guest, {})

    def test_first_and_last_beat_a_different_surname(self):
        # 'Christian Perez Gomez' is a different person from the roster's
        # 'Christian Perez'; the row that IS first+last takes the claim.
        host, guest = G.split(HOST, rows("Christian Perez Gomez",
                                         "Christian Alberto Perez"))
        self.assertEqual(reps(host), ["Christian Perez Gomez"])
        self.assertEqual(reps(guest[GUEST]), ["Christian Alberto Perez"])

    def test_a_first_name_alone_claims_nobody(self):
        host, guest = G.split(HOST, rows("Christian Alvarez"))
        self.assertEqual(len(host), 1)
        self.assertEqual(guest, {})


class SplitTests(unittest.TestCase):
    def test_order_is_preserved_on_both_sides(self):
        rs = rows("Hank Tran", "Nicholas Smedra", "Andrew Sanborn",
                  "Eduardo Alvarez")
        host, guest = G.split(HOST, rs)
        self.assertEqual(reps(host), ["Hank Tran", "Andrew Sanborn"])
        self.assertEqual(reps(guest[GUEST]),
                         ["Nicholas Smedra", "Eduardo Alvarez"])

    def test_no_row_lands_on_two_boards(self):
        rs = rows(*(G.roster(HOST, GUEST) + ["Hank Tran", "Andrew Sanborn"]))
        host, guest = G.split(HOST, rs)
        self.assertEqual(len(host) + sum(len(v) for v in guest.values()),
                         len(rs))
        self.assertFalse(set(reps(host)) & set(reps(guest[GUEST])))

    def test_a_guest_with_nobody_on_the_grid_leaves_the_board_alone(self):
        rs = rows("Hank Tran", "Andrew Sanborn")
        host, guest = G.split(HOST, rs, logfn=lambda m: None)
        self.assertEqual(host, rs)
        self.assertEqual(guest, {})

    def test_missing_rostered_reps_are_logged(self):
        said = []
        G.split(HOST, rows("Nicholas Smedra"), logfn=said.append)
        line = " ".join(said)
        self.assertIn("13 rostered rep(s) not on the grid", line)
        self.assertIn("Jorge Gramajo", line)

    def test_empty_day(self):
        host, guest = G.split(HOST, [])
        self.assertEqual(host, [])
        self.assertEqual(guest, {})


if __name__ == "__main__":
    unittest.main()
