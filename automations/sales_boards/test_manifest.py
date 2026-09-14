"""Pins the delivery proof a real Sales Boards post leaves behind.

2026-09-14: the BOX pass held on a rolled board, the next pass posted, and the
ticket stayed open anyway — "ran clean, but nothing can confirm it DELIVERED" —
because the report wrote no manifest and has no verify. This is what makes the
next one close itself.

Run:  python -m automations.sales_boards.test_manifest
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.sales_boards import run as R
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


class ARealPostLeavesProof(_TempManifestDir):

    def test_delivery_check_reads_it_as_delivered(self):
        now = dt.datetime.now()
        R._record_delivery("B2B posted", ["B2B"], real=True, run_ts=now)
        verdict = DC._from_manifest(R.REPORT_ID, now.date())
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict[0], DC.DELIVERED)

    def test_the_id_is_one_delivery_check_looks_under(self):
        self.assertIn(R.REPORT_ID, DC.manifest_ids(R.REPORT_ID))

    def test_yesterdays_proof_does_not_count_today(self):
        yesterday = dt.datetime.now() - dt.timedelta(days=1)
        R._record_delivery("old", ["B2B"], real=True, run_ts=yesterday)
        self.assertIsNone(DC._from_manifest(R.REPORT_ID, dt.date.today()))


class ATestPostLeavesNone(_TempManifestDir):
    """A dry run, a DM, a scratch channel or the sandbox delivered nothing."""

    def test_no_manifest_when_not_real(self):
        R._record_delivery("dm", ["B2B"], real=False, run_ts=dt.datetime.now())
        self.assertEqual(list(RM.MANIFEST_DIR.iterdir()), [])

    def test_only_the_real_rooms_off_prod_count(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SALES_BOARD_CHANNEL_ID", None)
            with mock.patch.object(R, "SHEET_ID", R.PROD_SHEET_ID):
                self.assertTrue(R._is_real_target())
                self.assertFalse(R._is_real_target("U123"))
            with mock.patch.object(R, "SHEET_ID", R.SANDBOX_SHEET_ID):
                self.assertFalse(R._is_real_target())
        with mock.patch.dict(os.environ, {"SALES_BOARD_CHANNEL_ID": "C1"}), \
                mock.patch.object(R, "SHEET_ID", R.PROD_SHEET_ID):
            self.assertFalse(R._is_real_target())


if __name__ == "__main__":
    unittest.main()
