"""Pins the delivery proof a --real Mobrium run leaves behind.

2026-09-11: a clean re-run could not close its own failure ticket — "ran clean,
but nothing can confirm it DELIVERED" — because the report wrote no manifest
and has no verify. Closed by hand; this is what makes the next one close itself.

Run:  python -m automations.mobrium_list.test_manifest
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.mobrium_list import run as R
from automations.shared import delivery_check as DC
from automations.shared import run_manifest as RM


class _TempManifestDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = RM.MANIFEST_DIR
        RM.MANIFEST_DIR = Path(self._tmp.name)

    def tearDown(self):
        RM.MANIFEST_DIR = self._orig
        self._tmp.cleanup()


class ARealRunLeavesProof(_TempManifestDir):

    def test_delivery_check_reads_it_as_delivered(self):
        now = dt.datetime.now()
        R._record_delivery("2 removed, 3 added", real=True, run_ts=now)
        verdict = DC._from_manifest(R.REPORT_ID, now.date())
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict[0], DC.DELIVERED)

    def test_the_id_is_one_delivery_check_looks_under(self):
        self.assertIn(R.REPORT_ID, DC.manifest_ids(R.REPORT_ID))

    def test_yesterdays_proof_does_not_count_today(self):
        yesterday = dt.datetime.now() - dt.timedelta(days=1)
        R._record_delivery("old", real=True, run_ts=yesterday)
        self.assertIsNone(DC._from_manifest(R.REPORT_ID, dt.date.today()))


class APreviewOrSandboxLeavesNone(_TempManifestDir):
    """Neither delivered anything, so neither may claim it did."""

    def test_no_manifest_without_real(self):
        R._record_delivery("preview", real=False, run_ts=dt.datetime.now())
        self.assertEqual(list(RM.MANIFEST_DIR.iterdir()), [])


class ItNeverCostsTheRun(unittest.TestCase):

    def test_a_broken_manifest_write_does_not_raise(self):
        orig = RM.write_manifest
        try:
            RM.write_manifest = lambda *a, **k: (_ for _ in ()).throw(
                OSError("disk full"))
            R._record_delivery("x", real=True)          # must not raise
        finally:
            RM.write_manifest = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
