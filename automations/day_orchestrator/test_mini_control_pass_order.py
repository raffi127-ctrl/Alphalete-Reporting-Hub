"""A DEPLOY MUST NOT WAIT OUT A BACKFILL.

2026-09-23: Eve queued ~90 `rerun ad_photo_threads` rows (ten offices x eight
dates, four to six minutes each). An `update` queued at 12:49 was still waiting
at 15:15, with two incident rows and a ping behind it. The lane was healthy the
whole time — it was grinding through the backfill in order — but from the
laptop that is indistinguishable from a dead poller, and it read as one for
most of an afternoon.

The read lane already solved this for reads. These pin the same rule for the
other cheap rows: bounded, idempotent plumbing goes first, reports keep FIFO
among themselves.
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator.mini_control import _pass_order


def _rows(*actions):
    return [{"Action": a, "Status": "queued"} for a in actions]


class PlumbingGoesFirst(unittest.TestCase):
    def test_an_update_behind_a_backfill_runs_first(self):
        rows = _rows(*(["rerun"] * 90 + ["update"]))
        first = _pass_order(rows)[0]
        self.assertEqual(first[0], 90, "the update still waits out the backfill")
        self.assertEqual(first[1]["Action"], "update")

    def test_every_plumbing_action_jumps(self):
        for action in ("update", "restart_poller", "ping"):
            rows = _rows("rerun", action)
            self.assertEqual(_pass_order(rows)[0][1]["Action"], action, action)

    def test_reports_keep_their_own_order(self):
        """A backfill runs oldest-first — that is what makes it re-runnable.
        Shuffling reports among themselves would post an office's days out of
        sequence."""
        rows = _rows("rerun", "rerun", "update", "rerun")
        reports = [i for i, r in _pass_order(rows) if r["Action"] == "rerun"]
        self.assertEqual(reports, [0, 1, 3])

    def test_plumbing_keeps_its_own_order(self):
        rows = _rows("update", "rerun", "ping")
        plumbing = [i for i, r in _pass_order(rows)
                    if r["Action"] in ("update", "ping")]
        self.assertEqual(plumbing, [0, 2])

    def test_every_row_is_still_offered_exactly_once(self):
        """Reordering must never DROP a row — the pass is also what fails an
        unknown action and what the cap message is written from."""
        rows = _rows("rerun", "update", "logtail", "rerun", "ping")
        self.assertEqual(sorted(i for i, _ in _pass_order(rows)),
                         list(range(len(rows))))

    def test_the_index_still_points_at_its_own_row(self):
        """The index becomes the SHEET ROW NUMBER (i + 2). If reordering broke
        that pairing, the poller would write one row's result onto another."""
        rows = _rows("rerun", "update", "rerun")
        for i, row in _pass_order(rows):
            self.assertIs(row, rows[i])

    def test_an_unknown_action_is_not_treated_as_plumbing(self):
        rows = _rows("rerun", "definitely_not_an_action")
        self.assertEqual(_pass_order(rows)[0][0], 0)


if __name__ == "__main__":
    unittest.main()
