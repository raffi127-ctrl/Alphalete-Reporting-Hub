"""Pins what a Credico fetch REPORTS about itself, so its ticket can close.

Written 2026-09-10. `failure-credico_fetch` opened when the session expired, was
fixed, re-ran clean at 11:02 — and stayed open anyway: `verify` said
`not_configured`, credico_fetch wrote no manifest, and delivery_check answers
UNKNOWN to that, which by design never closes a ticket
(automations/shared/delivery_check.py).

The download is observable, so the fix is a real observation rather than a
`close_on: exit_zero` declaration, and these tests hold the two halves together:
the manifest fetch_week writes, and the config block that reads it.

    python -m unittest automations.credico.test_fetch_manifest
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from automations.credico import report as R

SAT = "2026-09-12"
ABYL = "Abyl Acquisition Grp"
PHX = "Phoenix Acquisition"


class FetchManifestUnits(unittest.TestCase):

    def test_both_offices_downloaded_is_a_clean_run(self):
        got, missed, note = R._fetch_manifest_units(
            SAT, {ABYL: "ok", PHX: "ok"})
        self.assertEqual(got, sorted([ABYL, PHX]))
        self.assertEqual(missed, [])
        self.assertIn("2/2", note)
        self.assertNotIn("not published yet", note)

    def test_one_office_published_is_still_clean(self):
        """Credico publishes each office when it is ready — a one-office week
        must not paint credico_fetch red every Thursday. It says WHO is missing
        instead, because the fold fills that owner from Tableau alone and
        nothing else marks the week short."""
        got, missed, note = R._fetch_manifest_units(SAT, {PHX: "ok"})
        self.assertEqual((got, missed), ([PHX], []))
        self.assertIn("1/1", note)
        self.assertIn("Abel Draper", note)
        self.assertIn("not published yet", note)

    def test_an_office_that_did_not_download_is_a_failed_unit(self):
        got, missed, note = R._fetch_manifest_units(
            SAT, {PHX: "ok", ABYL: "no download (TimeoutError)"})
        self.assertEqual(got, [PHX])
        self.assertEqual(missed, [ABYL])

    def test_a_week_with_no_office_at_all_is_not_a_delivery(self):
        """The empty week is the one that used to read as success: zero nodes,
        zero errors, exit 0, nothing for dd_populate to fold."""
        got, missed, note = R._fetch_manifest_units(SAT, {})
        self.assertEqual(got, [])
        self.assertTrue(missed, "an empty week must name a failed unit")
        self.assertIn(SAT, missed[0])
        self.assertIn(SAT, note)

    def test_the_note_names_the_offices_that_came(self):
        _got, _missed, note = R._fetch_manifest_units(SAT, {PHX: "ok"})
        self.assertIn(PHX, note)
        self.assertIn(SAT, note)


class ManifestWriting(unittest.TestCase):

    def test_it_files_under_the_schedule_config_id(self):
        seen = {}

        class _Stub:
            @staticmethod
            def write_manifest(report_id, **kw):
                seen.update(kw, report_id=report_id)

        import sys
        real = sys.modules.get("automations.shared.run_manifest")
        sys.modules["automations.shared.run_manifest"] = _Stub
        try:
            R._write_fetch_manifest("9.6.26", SAT, {PHX: "ok"})
        finally:
            if real is None:
                sys.modules.pop("automations.shared.run_manifest", None)
            else:
                sys.modules["automations.shared.run_manifest"] = real
        self.assertEqual(seen["report_id"], R.FETCH_REPORT_ID)
        self.assertEqual(seen["succeeded"], [PHX])
        self.assertEqual(seen["failed"], [])
        self.assertEqual(seen["kind"], "office")
        self.assertIn("--week", seen["retry_args"])
        self.assertIn("9.6.26", seen["retry_args"])

    def test_a_manifest_that_cannot_be_written_never_loses_the_download(self):
        class _Boom:
            @staticmethod
            def write_manifest(*a, **k):
                raise RuntimeError("disk full")

        import sys
        real = sys.modules.get("automations.shared.run_manifest")
        sys.modules["automations.shared.run_manifest"] = _Boom
        try:
            R._write_fetch_manifest("9.6.26", SAT, {PHX: "ok"})   # must not raise
        finally:
            if real is None:
                sys.modules.pop("automations.shared.run_manifest", None)
            else:
                sys.modules["automations.shared.run_manifest"] = real


class OfficeSpellings(unittest.TestCase):

    def test_the_fee_report_tree_spellings_resolve_to_owners(self):
        """The note names the owner who has not been published yet, and it can
        only do that if the TREE's spelling maps. The tree is shorter than the
        "Select Office" dropdown COMPANY_TO_OWNER was built from — `Abyl
        Acquisition Grp`, not `Abyl Acquisition Group, Inc.`"""
        from automations.override_bulletin.dd_rows import COMPANY_TO_OWNER
        for node, owner in ((ABYL, "Abel Draper"), (PHX, "Jahvid Thompson")):
            self.assertEqual(COMPANY_TO_OWNER.get(R._ckey(node)), owner, node)


class ConfigBlock(unittest.TestCase):

    def _report(self):
        cfg = Path(R.__file__).resolve().parents[2] / "automations" / \
            "day_orchestrator" / "schedule_config.json"
        return json.loads(cfg.read_text(encoding="utf-8"))["reports"]["credico_fetch"]

    def test_verify_reads_the_manifest_this_module_writes(self):
        v = self._report().get("verify") or {}
        self.assertEqual(v.get("type"), "manifest")
        self.assertEqual(v.get("report_id"), R.FETCH_REPORT_ID)

    def test_it_is_not_declared_unverifiable(self):
        """close_on: exit_zero is for probes and installers. Putting it on a
        report whose delivery CAN be seen rebuilds the false green that
        delivery_check was written to end."""
        self.assertNotIn("close_on", self._report())


if __name__ == "__main__":
    unittest.main()
