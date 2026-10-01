"""Past the B2B floor, a live pass re-pulls the ATT order log itself.

2026-10-01: att_order_log ran once at 04:14, before Tableau had 9/30, and no
later pass ever brought the late sales in.

    python -m unittest automations.vantura_orderlog_sales.test_repull -v
"""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from automations.vantura_orderlog_sales import run


class RepullTest(unittest.TestCase):
    def _repull(self, **kw):
        with mock.patch.object(run, "_log"), \
                mock.patch("subprocess.run", **kw) as sp:
            return run.repull_att(), sp

    def test_runs_att_order_log_sheet(self):
        ok, sp = self._repull(return_value=mock.Mock(returncode=0, stdout=""))
        self.assertTrue(ok)
        cmd = sp.call_args.args[0]
        self.assertEqual(cmd[1:], ["-m", "automations.att_order_log.run",
                                   "--sheet"])

    def test_failed_pull_returns_false(self):
        ok, _ = self._repull(return_value=mock.Mock(returncode=1, stdout=""))
        self.assertFalse(ok)

    def test_timeout_never_raises(self):
        ok, _ = self._repull(side_effect=subprocess.TimeoutExpired("x", 1))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
