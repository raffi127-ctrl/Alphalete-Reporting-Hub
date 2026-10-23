"""A dead ownerville session must FAIL every office in the slot, not crash it.

2026-10-21: the 9 PM Central tick's pull raised "ownerville session expired or
missing" straight out of build(). No "eod: posted= skipped= failed=" line was
printed, knocks_intraday.sh took that as a quiet tick, and nothing was published
or alerted — Cody, Haytham and Raf had no board and nobody was told.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.knocks_intraday import roster
from automations.knocks_intraday import run as RUN
from automations.knocks_intraday import schedule as S


def _dead(*_a, **_k):
    raise RuntimeError("ownerville session expired or missing, and the "
                       "unattended login did not reach a live session either")


class DeadSessionTest(unittest.TestCase):
    def test_every_office_comes_back_failed_and_the_slot_reports_it(self):
        offices = roster.enrolled("eod")[:2]
        self.assertTrue(offices, "need at least one enrolled office")
        day = dt.date(2026, 10, 21)
        slot = S.SLOTS_BY_KEY["eod"]
        lines = []
        with mock.patch("automations.rashad_metrics.knocks_pull."
                        "pull_offices_days", _dead):
            results = RUN.build(slot, [(o, day) for o in offices],
                                logfn=lines.append)
        self.assertEqual(len(results), len(offices))
        self.assertTrue(all(isinstance(r["error"], RuntimeError)
                            for r in results))
        rc = RUN.post(results, slot, dry_run=True, logfn=lines.append)
        self.assertEqual(rc, 1)
        self.assertTrue(any(f"failed={len(offices)}" in l for l in lines),
                        lines)


if __name__ == "__main__":
    unittest.main()
