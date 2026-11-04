"""A last-week pull stops when the run is nearly out of time (2026-11-01: one new
rep sent both morning runs into b2b/nds retries until the 45m kill).

Offline: no Sheet, no Tableau.
"""
from __future__ import annotations

import datetime as dt
import time
import unittest

from automations.org_sales_board import captainship as cap

TODAY = dt.date(2026, 11, 1)


class ProgramPullDeadline(unittest.TestCase):
    def pull(self, deadline):
        calls = []

        def resolve_csv(label, spec):
            calls.append(label)
            raise RuntimeError("Could not find the sheet in the Crosstab dialog")

        lines = []
        orig = cap._PROG_PULL_BACKOFF_S
        cap._PROG_PULL_BACKOFF_S = 0
        try:
            prog, failed = cap.pull_programs(None, TODAY, resolve_csv=resolve_csv,
                                             logfn=lines.append, deadline=deadline)
        finally:
            cap._PROG_PULL_BACKOFF_S = orig
        return prog, failed, calls, lines

    def test_out_of_time_starts_nothing_and_names_every_program(self):
        prog, failed, calls, lines = self.pull(time.monotonic() + 60)
        self.assertEqual(calls, [])
        self.assertEqual(set(failed), set(cap.PROGRAMS))
        self.assertTrue(all(prog[k] == {} for k in cap.PROGRAMS))
        self.assertTrue(any("min left" in line for line in lines))

    def test_time_left_keeps_all_the_retries(self):
        _, failed, calls, _ = self.pull(time.monotonic() + 3600)
        self.assertEqual(len(calls), cap._PROG_PULL_TRIES * len(cap.PROGRAMS))
        self.assertEqual(set(failed), set(cap.PROGRAMS))

    def test_no_deadline_behaves_as_before(self):
        _, _, calls, _ = self.pull(None)
        self.assertEqual(len(calls), cap._PROG_PULL_TRIES * len(cap.PROGRAMS))


if __name__ == "__main__":
    unittest.main()
