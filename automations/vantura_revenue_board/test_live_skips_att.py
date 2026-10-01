"""A live pass never pulls or waits on the ATT export — the B2B Metrics
runner owns the ATT board. 2026-10-01: the 05:20 / 05:50 passes held for 9/30
rows they were never going to post, went `partial`, and opened a ticket.

    python -m unittest automations.vantura_revenue_board.test_live_skips_att -v
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.vantura_revenue_board import run

THU_0520 = dt.datetime(2026, 10, 1, 5, 20)


class _Clock(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return THU_0520


class LiveSkipsAtt(unittest.TestCase):
    def _main(self, argv):
        with mock.patch.object(run.dt, "datetime", _Clock), \
                mock.patch.object(run, "load_priced",
                                  return_value=({}, {})) as lp, \
                mock.patch("automations.captainship_boards.run.pull_orderlog"
                           ) as pull, \
                mock.patch.object(run, "post", return_value=0):
            rc = run.main(["--date", "2026-09-30", "--only", "att"] + argv)
        return rc, lp, pull

    def test_live_pass_does_not_hold_on_att(self):
        rc, lp, pull = self._main(["--post"])
        self.assertEqual(rc, 0)
        lp.assert_not_called()
        pull.assert_not_called()

    def test_preview_still_renders_and_holds_on_an_empty_day(self):
        for argv in ([], ["--post", "--no-post"], ["--dm", "U123"]):
            rc, lp, _ = self._main(argv)
            self.assertEqual(rc, 75, argv)
            lp.assert_called_once()


if __name__ == "__main__":
    unittest.main()
