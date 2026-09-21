"""A live pass that lands a board writes the run manifest; a dry run, a DM
test, a hold or an ATT-only pass does not.

2026-09-21: the ticket stayed open after a clean pass — "ran clean, but
nothing can confirm it DELIVERED" — because nothing wrote a manifest.

    python -m unittest automations.vantura_revenue_board.test_manifest -v
"""
from __future__ import annotations

import datetime as dt
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.vantura_revenue_board import run

DAY = dt.date(2026, 9, 19)                          # a Saturday


class ManifestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.close()
        self.csv = tmp.name
        self.addCleanup(Path(self.csv).unlink)

    def _main(self, argv, *, post_rc=0, only="box"):
        per_box = {"rep": {"days": {DAY: 1}}}
        done = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(run, "load_box_priced", return_value=per_box), \
                mock.patch.object(run, "build_rows",
                                  return_value=([], {"bonus": 0})), \
                mock.patch.object(run, "render",
                                  side_effect=lambda *a, **k: a[4]), \
                mock.patch.object(run, "post", return_value=post_rc) as post, \
                mock.patch("subprocess.run", return_value=done), \
                mock.patch("automations.shared.run_manifest.write_manifest"
                           ) as wm:
            rc = run.main(["--date", DAY.isoformat(), "--only", only,
                           "--box-csv", self.csv] + argv)
        return rc, wm, post

    def test_live_post_writes_proof(self):
        rc, wm, _ = self._main(["--post"])
        self.assertEqual(rc, 0)
        wm.assert_called_once()
        self.assertEqual(wm.call_args.args[0], "vantura_revenue_board")
        self.assertEqual(wm.call_args.kwargs["succeeded"],
                         ["Box Revenue Board 9.19"])

    def test_dry_and_dm_and_no_post_write_nothing(self):
        for argv in ([], ["--dm", "U123"], ["--post", "--no-post"]):
            rc, wm, _ = self._main(argv)
            self.assertEqual(rc, 0)
            wm.assert_not_called()

    def test_held_thread_writes_nothing(self):
        rc, wm, _ = self._main(["--post"], post_rc=75)
        self.assertEqual(rc, 75)
        wm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
