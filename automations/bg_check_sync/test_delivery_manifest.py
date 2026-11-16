"""Pins the delivery proof a real BG Check Sync leaves behind.

2026-11-15: the 18:11 run failed, a later pass went clean, and the ticket stayed
open on "ran clean, but nothing can confirm it DELIVERED" — this report had no
verify and wrote no manifest, so publish_done painted the Hub tile green and
left the closer nothing to read.

The one that would have bitten quietly: the id. The incident is keyed
`failure-bg_check_sync` and the Hub row says `bg_check_sync`, but the
schedule_config key is `bg_check_sync_post`. delivery_check.manifest_ids only
tries the id it is asked about plus the dashed spelling — so a manifest filed
under the config key would never be found, and the symptom would look like a
design flaw rather than a lookup mistake (the same trap caught on 2026-09-09).

Run:  python -m unittest automations.bg_check_sync.test_delivery_manifest
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

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


def _run_mod():
    from automations.bg_check_sync import run as R
    return R


class ARealSyncLeavesProof(_TempManifestDir):

    def test_delivery_check_reads_it_as_delivered(self):
        R = _run_mod()
        R._record_delivery()
        verdict = DC._from_manifest(R.REPORT_ID, dt.date.today())
        self.assertIsNotNone(verdict, "a real run wrote no manifest")
        self.assertEqual(verdict[0], DC.DELIVERED)

    def test_the_id_is_the_one_the_hub_row_and_incident_use(self):
        R = _run_mod()
        self.assertEqual(R.REPORT_ID, "bg_check_sync")
        self.assertIn(R.REPORT_ID, DC.manifest_ids(R.REPORT_ID))

    def test_the_config_key_is_not_where_the_proof_goes(self):
        # Filing under the schedule_config key would be invisible to the
        # closer. This is the assertion that says why REPORT_ID differs.
        R = _run_mod()
        self.assertNotIn(R.REPORT_ID, DC.manifest_ids("bg_check_sync_post"))


class TheHubRowAndTheManifestAgree(unittest.TestCase):
    """If these two ever drift, the tile goes green and the ticket stays open —
    which is exactly the 11-15 symptom."""

    def test_both_publishes_use_report_id(self):
        import inspect
        R = _run_mod()
        src = inspect.getsource(R)
        self.assertNotIn('publish_running("bg_check_sync"', src)
        self.assertNotIn('publish_done("bg_check_sync"', src)


class TheManifestNeverBreaksTheSync(_TempManifestDir):

    def test_a_broken_manifest_write_is_swallowed(self):
        R = _run_mod()
        RM.MANIFEST_DIR = Path("/nonexistent-path-for-this-test/nope")
        R._record_delivery()        # must not raise


if __name__ == "__main__":
    unittest.main()
