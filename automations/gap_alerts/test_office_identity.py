"""No office may publish another office's reps.

Two separate failures on 2026-09-01, one root cause: ownerville hands an
impersonated session the SAME rqst as master, so nothing in the token says
which office a fetch answered for, and an impersonation that does not take
produces plausible numbers instead of an error.

  * Jay's board came back with Raf's exact 37 reps and posted into the Energy
    Wells chat as "Jay — AT&T".
  * Calvin's seven gap reps went out in Raf's Alphalete Partners chat, beside a
    board image that was correctly Raf's. Someone there asked "who are these?"
    — the only reason it was caught.

Identity cannot be read off the session, so both guards read it off the DATA.
Offline: no ownerville, no network.
"""
import unittest

from automations.gap_alerts import run as R


def _rows(*names):
    """Rep ids derived from the NAME, because ownerville's are globally unique
    — numbering them per-call would make two different offices collide in the
    test and nowhere else."""
    return [{"ID": str(9_000_000 + (abs(hash(n)) % 900_000)), "Rep": n}
            for n in names]


def _gaps(*names):
    return [{"name": n, "minutesSinceLastKnock": 30} for n in names]


RAF = {"key": "rafael", "name": "Rafael Hidalgo", "ov": "master"}
CALVIN = {"key": "calvin", "name": "Calvin Ribera", "ov": "impersonate"}
JAY = {"key": "jay_att", "name": "Jay Turnage", "ov": "impersonate"}


class GapListMustBeThisOfficesPeople(unittest.TestCase):
    def test_a_foreign_gap_list_is_dropped_whole(self):
        """Calvin's reps against Raf's board: the exact Partners-chat bug."""
        board = _rows("Alyssa Moreno", "Zoria Johnson")
        foreign = _gaps("Maurice Dupree", "Cooper Summerville")
        self.assertEqual(R._own_reps_only(RAF, foreign, board), [])

    def test_this_offices_own_gap_list_survives_untouched(self):
        board = _rows("Alyssa Moreno", "Zoria Johnson")
        mine = _gaps("Zoria Johnson", "Alyssa Moreno")
        self.assertEqual(R._own_reps_only(RAF, mine, board), mine)

    def test_strays_are_dropped_and_the_rest_kept(self):
        board = _rows("Alyssa Moreno", "Zoria Johnson")
        mixed = _gaps("Alyssa Moreno", "Maurice Dupree")
        kept = R._own_reps_only(RAF, mixed, board)
        self.assertEqual([r["name"] for r in kept], ["Alyssa Moreno"])

    def test_name_spelling_is_normalised_not_exact_matched(self):
        """Spacing/case drift between the two pulls must not read as foreign —
        dropping a real gap list is its own failure."""
        board = _rows("Alyssa  Moreno")
        self.assertEqual(len(R._own_reps_only(RAF, _gaps("alyssa moreno"), board)), 1)

    def test_an_empty_board_does_not_veto_the_gap_list(self):
        """No board rows means nothing to check against, not 'everyone is
        foreign' — a gaps-only office would otherwise lose its whole point."""
        mine = _gaps("Alyssa Moreno")
        self.assertEqual(R._own_reps_only(RAF, mine, []), mine)


class IdenticalRepSetsCannotBothBeReal(unittest.TestCase):
    def _out(self, **by_key):
        return {k: (["board.png"], rows, None) for k, rows in by_key.items()}

    def test_the_impersonated_collider_is_dropped_and_master_kept(self):
        same = _rows("Alyssa Moreno", "Zoria Johnson")
        out = R._drop_duplicate_offices(
            self._out(rafael=same, jay_att=list(same)),
            [(RAF, ""), (JAY, "")])
        self.assertIsNone(out["rafael"][2], "master must survive")
        self.assertIsNotNone(out["jay_att"][2], "the impostor must not publish")
        self.assertEqual(out["jay_att"][0], [], "and must carry no board")
        self.assertIn("fell", str(out["jay_att"][2]))

    def test_two_impersonated_colliders_both_go(self):
        """With no verified office in the pair, neither can be trusted."""
        same = _rows("Alyssa Moreno")
        out = R._drop_duplicate_offices(
            self._out(calvin=same, jay_att=list(same)),
            [(CALVIN, ""), (JAY, "")])
        self.assertIsNotNone(out["calvin"][2])
        self.assertIsNotNone(out["jay_att"][2])

    def test_genuinely_different_offices_are_left_alone(self):
        out = R._drop_duplicate_offices(
            self._out(rafael=_rows("Alyssa Moreno"),
                      calvin=_rows("Maurice Dupree")),
            [(RAF, ""), (CALVIN, "")])
        self.assertIsNone(out["rafael"][2])
        self.assertIsNone(out["calvin"][2])

    def test_two_empty_offices_are_not_duplicates(self):
        """Before the field is out everyone has no rows; that is not a
        collision, and calling it one would blank every early board."""
        out = R._drop_duplicate_offices(
            self._out(rafael=[], calvin=[]), [(RAF, ""), (CALVIN, "")])
        self.assertIsNone(out["rafael"][2])
        self.assertIsNone(out["calvin"][2])


if __name__ == "__main__":
    unittest.main()
