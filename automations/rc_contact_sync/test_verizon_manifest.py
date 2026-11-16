"""Pins the delivery proof a real Verizon contact sync leaves behind.

2026-11-15: `rc_contact_sync_verizon` failed, a later run went clean, and the
ticket stayed open all day anyway — "ran clean, but nothing can confirm it
DELIVERED, so this stays open" — because this entry point wrote no manifest
and has no verify. Its NDS siblings (rc_contact_sync, rc_contact_sync_raf)
had written one all along; only the Verizon one was missed.

The three things that have to stay true, and each one broke something real
somewhere in this repo before it was pinned:

  1. a LIVE run leaves proof delivery_check reads as DELIVERED
  2. a DRY RUN leaves none — a preview created no contacts, so letting it
     close the ticket marks a real miss delivered
  3. the id is one delivery_check actually asks under (the dashed-vs-undered
     lookup bug that almost shipped on 2026-09-09)

Run:  python -m unittest automations.rc_contact_sync.test_verizon_manifest
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.rc_contact_sync import verizon as V
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


class ARealSyncLeavesProof(_TempManifestDir):

    def test_delivery_check_reads_a_clean_live_run_as_delivered(self):
        V._manifest([], dry_run=False, note="2 added, 5 already there")
        verdict = DC._from_manifest(V.REPORT_ID, dt.date.today())
        self.assertIsNotNone(verdict, "a live run wrote no manifest")
        self.assertEqual(verdict[0], DC.DELIVERED)

    def test_the_id_is_one_delivery_check_looks_under(self):
        self.assertIn(V.REPORT_ID, DC.manifest_ids(V.REPORT_ID))

    def test_a_quiet_day_still_publishes(self):
        # Credico pays two weeks behind, so "no live line" is the normal
        # result on plenty of days. If that path wrote nothing, every quiet
        # day would hold the ticket open.
        V._manifest([], dry_run=False, note="no live Verizon line")
        self.assertIsNotNone(DC._from_manifest(V.REPORT_ID, dt.date.today()))


class ADryRunIsNotProof(_TempManifestDir):
    """This module is dry-run BY DEFAULT, so this is the common path, not an
    edge case. run_manifest's `dry_run=` flag does NOT protect it — that flag
    only silences the Slack side ("A dry run may write its manifest; it may
    not speak in the channel"), so _manifest has to skip the write itself."""

    def test_a_preview_leaves_no_manifest(self):
        V._manifest([], dry_run=True, note="would create 3")
        self.assertIsNone(DC._from_manifest(V.REPORT_ID, dt.date.today()),
                          "a dry run must never close the ticket — it created "
                          "no contacts")

    def test_the_flag_alone_would_not_have_been_enough(self):
        # Guards the REASON for the early return above: if someone 'simplifies'
        # _manifest back to just forwarding dry_run=, this is what breaks.
        RM.write_manifest(V.REPORT_ID, failed=[], kind="part",
                          note="flag-only", dry_run=True)
        self.assertIsNotNone(
            DC._from_manifest(V.REPORT_ID, dt.date.today()),
            "run_manifest's dry_run= is about the alert, not the file — if "
            "that ever changes, _manifest's early return can be relaxed")


class AFailureNamesWhoMissed(_TempManifestDir):

    def test_the_failed_customers_are_in_the_manifest(self):
        V._manifest(["Jane D (Taylor)"], dry_run=False, note="1 failed")
        m = RM.read_manifest(V.REPORT_ID) or {}
        self.assertIn("Jane D (Taylor)", m.get("failed") or [])

    def test_a_failure_is_not_read_as_delivered(self):
        V._manifest(["Jane D (Taylor)"], dry_run=False, note="1 failed")
        verdict = DC._from_manifest(V.REPORT_ID, dt.date.today())
        if verdict is not None:
            self.assertNotEqual(verdict[0], DC.DELIVERED)


class TheManifestNeverBreaksTheSync(_TempManifestDir):

    def test_a_broken_manifest_write_is_swallowed(self):
        # The contacts are in the address book by this point; a bookkeeping
        # failure must not turn a good run into a crash.
        RM.MANIFEST_DIR = Path("/nonexistent-path-for-this-test/nope")
        V._manifest([], dry_run=False, note="x")   # must not raise


if __name__ == "__main__":
    unittest.main()
