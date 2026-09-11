"""Terminated ICDs stay off the knock boards AND out of the access watch.

2026-09-11: knocks_access_watch posted "Office Access granted — chan/Eric
Martinez" a day after his office closed. He is still on Chan's Org Sales Board
block on purpose, so only the 'Terminated ICDs' tab can say he's gone.

    python -m unittest automations.captainship_drafts.test_knocks_terminated
"""
import types
import unittest
from unittest import mock

from automations.captainship_drafts import knock_dispo_images as KD

ROSTER = ["Chan Park", "Eric Martinez", "Carissa Ng"]


def _lookup(*gone):
    low = {g.lower() for g in gone}
    return lambda name: name.lower() in low


def _board_patches():
    """Stand in for the Org Sales Board: one Chan block holding ROSTER."""
    from automations.captainship_drafts import sales_board as sb
    from automations.org_sales_board import captainship as cap
    anchor = types.SimpleNamespace(
        leaderboard=[(i, n) for i, n in enumerate(ROSTER)], daily=[])
    return [
        mock.patch.dict(sb.CAPTAIN_TOKEN, {"chan": "chan"}),
        mock.patch.object(cap, "discover_captainships",
                          lambda grid: [("CHAN'S CAPTAINSHIP", "")]),
        mock.patch.object(cap, "_cap_key", lambda t: t),
        mock.patch.object(cap, "find_captainship", lambda grid, t: anchor),
    ]


class DropTerminatedTests(unittest.TestCase):
    def test_terminated_owner_is_removed_order_kept(self):
        got = KD.drop_terminated(ROSTER, _lookup("Eric Martinez"),
                                 logfn=lambda *_: None)
        self.assertEqual(got, ["Chan Park", "Carissa Ng"])

    def test_nobody_terminated_keeps_everyone(self):
        self.assertEqual(
            KD.drop_terminated(ROSTER, _lookup(), logfn=lambda *_: None),
            ROSTER)

    def test_a_broken_lookup_never_empties_the_roster(self):
        def boom(_name):
            raise RuntimeError("sheet down")
        self.assertEqual(
            KD.drop_terminated(ROSTER, boom, logfn=lambda *_: None), ROSTER)

    def test_the_drop_is_logged(self):
        lines = []
        KD.drop_terminated(ROSTER, _lookup("Eric Martinez"), logfn=lines.append)
        self.assertEqual(len(lines), 1)
        self.assertIn("Eric Martinez", lines[0])


class RostersSkipTerminatedTests(unittest.TestCase):
    def _run(self, fn):
        patches = _board_patches()
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in reversed(patches):
                p.stop()

    def test_knock_boards_leave_him_out(self):
        got = self._run(lambda: KD.owner_names(
            "chan", grid=[], is_terminated=_lookup("Eric Martinez")))
        self.assertEqual(got, ["Chan Park", "Carissa Ng"])

    def test_access_watch_leaves_him_out(self):
        from automations.knocks_access_watch import audit as A
        with mock.patch.object(A, "CAPTAINS", ("chan",)):
            got = self._run(lambda: A.rosters(
                grid=[], is_terminated=_lookup("Eric Martinez")))
        self.assertEqual(got["chan"][1], ["Chan Park", "Carissa Ng"])


if __name__ == "__main__":
    unittest.main()
