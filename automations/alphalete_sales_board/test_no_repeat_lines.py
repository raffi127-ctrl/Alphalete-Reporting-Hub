"""Two reps must not get the same sentence on Raf's board.

2026-09-18: "Ian said watch this" posted directly under "Jacari said watch
this". Each line goes out as its OWN Slack message and Slack groups them under
one timestamp, so a repeat reads exactly like a repeat.

The ICD poster was given batching an hour before this file was. Same
one-place-not-the-other that has cost a day at a time all week -- the shared
wording lives in sale_hype, and two callers reach it.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest

from automations.alphalete_sales_board import notify as N
from automations.shared import sale_hype as H

DAY = dt.date(2026, 9, 18)
ONE = {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 1}


class RafsBoardDoesNotRepeatItselfTest(unittest.TestCase):
    def setUp(self):
        self._orig = H.RECENT_LINES_PATH
        H.RECENT_LINES_PATH = pathlib.Path(tempfile.mkdtemp()) / "recent.json"
        self.addCleanup(lambda: setattr(H, "RECENT_LINES_PATH", self._orig))

    def _batch(self, gained):
        return N.hype_batch([r for r, _d in sorted(gained.items())],
                            gained, DAY)

    def test_a_colliding_pair_is_separated(self):
        """'Ao Test' and 'Au Test' hash to the same line on their own."""
        out = self._batch({"Ao Test": dict(ONE), "Au Test": dict(ONE)})
        stripped = [l.replace("Ao", "").replace("Au", "") for l in out]
        self.assertEqual(len(set(stripped)), 2, out)

    def test_every_rep_still_gets_a_line(self):
        out = self._batch({"A B": dict(ONE), "C D": dict(ONE),
                           "E F": dict(ONE)})
        self.assertEqual(len(out), 3)

    def test_it_names_the_right_rep(self):
        out = self._batch({"Jacari Woods": dict(ONE)})
        self.assertIn("Jacari", out[0])

    def test_consecutive_posts_differ_too(self):
        """They are separate Slack messages a tick apart, so the memory has to
        survive between calls -- not only within one."""
        first = self._batch({"Ian D": dict(ONE)})
        second = self._batch({"Jacari W": dict(ONE)})
        self.assertNotEqual(first[0].replace("Ian", ""),
                            second[0].replace("Jacari", ""))

    def test_the_board_is_att(self):
        """Box's contract wording is chosen by campaign, not by which file
        asked -- the AO board takes the default."""
        out = self._batch({"A B": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 3}})
        self.assertNotIn("contract", out[0].lower())


if __name__ == "__main__":
    unittest.main()
