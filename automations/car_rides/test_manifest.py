"""A live pass files proof of what it reconciled; a dry run files nothing.

2026-09-24: failure-car_rides stayed open after a clean pass — "ran clean, but
nothing can confirm it DELIVERED" — because `verify` was null and this module
wrote no manifest. These hold the two halves of the fix together: the split
between a FAILURE (the pass could not reconcile) and a FINDING (it reconciled
and is reporting what only Carlos can fix on the board), and the config block
that reads the manifest back.

    python -m unittest automations.car_rides.test_manifest -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.car_rides import run
from automations.shared import delivery_check, run_manifest

CHANGES = {"att": 2, "box": 0}
BOTH = ["B2B AT&T SBS", "B2B-BOX-Energy"]


class FileManifestTest(unittest.TestCase):
    def _call(self, **kw):
        args = dict(live=True, failures=[], findings=[], tab_ok=True,
                    changes=CHANGES, reconciled=list(BOTH))
        args.update(kw)
        with mock.patch.object(run_manifest, "write_manifest") as wm:
            run._file_manifest(**args)
        return wm

    def test_a_dry_run_proves_nothing(self):
        """A plan that applied no edits has no delivery to record — and a
        manifest left behind by a rehearsal would later be read as proof."""
        self._call(live=False).assert_not_called()
        self._call(live=False, failures=["session gone"]).assert_not_called()

    def test_clean_live_pass_files_a_clean_manifest(self):
        wm = self._call()
        wm.assert_called_once()
        self.assertEqual(wm.call_args.args[0], "car_rides")
        kw = wm.call_args.kwargs
        self.assertTrue(kw["ok"])
        self.assertEqual(kw["failed"], [])
        self.assertIn("B2B AT&T SBS", kw["note"])
        self.assertIn("2 edit(s) applied", kw["note"])

    def test_board_findings_are_a_delivery_not_a_failure(self):
        """"Ambiguous, skipped" is the run doing its job. A re-run cannot fix
        the board, so the ticket must not wait on one."""
        wm = self._call(findings=["B2B AT&T SBS: Jose: no territory found"])
        kw = wm.call_args.kwargs
        self.assertEqual(kw["kind"], "finding")
        self.assertFalse(kw["ok"])
        self.assertEqual(len(kw["failed"]), 1)

    def test_findings_do_not_page_the_channel_nine_times_a_morning(self):
        """Nine passes, and flags like "first sighting; will confirm next run"
        are the rule working. They belong on the card, not in #corrections."""
        self.assertFalse(self._call(findings=["x"]).call_args.kwargs["alert"])

    def test_a_pass_that_could_not_reconcile_holds_the_ticket_open(self):
        wm = self._call(failures=["OwnerVille session missing/stale"],
                        reconciled=[])
        kw = wm.call_args.kwargs
        self.assertNotEqual(kw["kind"], "finding")   # 'finding' reads DELIVERED
        self.assertEqual(kw["failed"], ["OwnerVille session missing/stale"])
        self.assertTrue(kw["remediation"]["fix"])

    def test_one_campaign_home_and_one_lost_is_partial_not_total(self):
        wm = self._call(failures=["B2B-BOX-Energy: 0 territories loaded"],
                        reconciled=["B2B AT&T SBS"])
        self.assertEqual(wm.call_args.kwargs["succeeded"], ["B2B AT&T SBS"])

    def test_a_report_tab_that_never_published_is_a_failure(self):
        """The tab is where Carlos reads the flags — a run that could not write
        it delivered half of what it exists to deliver."""
        wm = self._call(tab_ok=False)
        failed = wm.call_args.kwargs["failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn(run.REPORT_TAB, failed[0])

    def test_findings_never_swallow_a_failure(self):
        wm = self._call(failures=["edit failed on 'Team Diego'"],
                        findings=["stale territory 'Team Luis'"])
        self.assertNotEqual(wm.call_args.kwargs["kind"], "finding")


class ConfigTest(unittest.TestCase):
    def setUp(self):
        cfg = json.loads((Path(run.REPO_ROOT) / "automations" /
                          "day_orchestrator" / "schedule_config.json"
                          ).read_text(encoding="utf-8"))
        self.rec = cfg["reports"]["car_rides"]

    def test_a_manifest_verifier_would_hold_a_good_morning_open(self):
        """`verify` stays null ON PURPOSE (same as vantura_board_audit and
        digi_docs). delivery_check asks _from_verifier BEFORE _from_manifest,
        and reconcile._verify_manifest reads a kind='finding' ok=false as a
        FAILURE — so wiring one here would hold the ticket open on exactly the
        mornings the run worked, with no re-run able to clear it."""
        self.assertIsNone(self.rec["verify"])
        self.assertIn("finding", self.rec["_verify_note"])

    def test_not_declared_unobservable(self):
        """close_on: exit_zero is for probes and installers. This one leaves
        reconciled territories and a report tab anybody can open."""
        self.assertNotIn("close_on", self.rec)


class ChainTest(unittest.TestCase):
    """The manifest this writes is the one delivery_check reads back — the
    three verdicts the incident thread turns on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in ((run_manifest, Path(self.tmp.name)),):
            patch = mock.patch.object(target, "MANIFEST_DIR", value)
            patch.start()
            self.addCleanup(patch.stop)

    def _verdict(self, **kw):
        with mock.patch("automations.shared.section_drop_alert.alert"), \
                mock.patch("automations.shared.section_drop_alert.resolved"), \
                mock.patch.object(delivery_check, "_from_phases",
                                  return_value=None):
            run._file_manifest(live=True, tab_ok=True, changes=CHANGES,
                               reconciled=list(BOTH),
                               failures=kw.get("failures", []),
                               findings=kw.get("findings", []))
            return delivery_check.verdict("car_rides")[0]

    def test_a_clean_pass_closes_its_own_ticket(self):
        self.assertEqual(self._verdict(), delivery_check.DELIVERED)

    def test_a_pass_with_board_findings_also_closes_it(self):
        """THE ONE THIS FIX TURNS ON. A re-run cannot create Carlos's missing
        team, so a finding must not hold the ticket."""
        self.assertEqual(self._verdict(findings=["Jose: no territory found"]),
                         delivery_check.DELIVERED)

    def test_a_pass_that_reconciled_nothing_does_not(self):
        self.assertEqual(self._verdict(failures=["0 territories loaded"]),
                         delivery_check.NOT_DELIVERED)


if __name__ == "__main__":
    unittest.main()
