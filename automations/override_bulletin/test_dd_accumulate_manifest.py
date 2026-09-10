"""Tests for the run-manifest `dd_special_accumulate` files
(`dd_search._write_accumulate_manifest`).

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.override_bulletin.test_dd_accumulate_manifest

WHY (2026-09-10). The report's `verify` block said `not_configured`, so
`delivery_check` answered UNKNOWN and `failure-dd_special_accumulate` could not
close itself even on the run that fixed it — the same hole credico_fetch had
that morning. The write is observable, so it is now OBSERVED: one manifest unit
per special-case row, naming what took the figure and what could not be placed.

Slack safety: `write_manifest` pings #claudecorrections on any recorded failure,
and this machine has a live token. These tests patch the ATTRIBUTE on the real
`run_manifest` module (never `sys.modules`, which a `from … import …` walks
straight past — 2026-09-07) and setUpModule poisons the token as a second
barrier, so a patch that breaks gives invalid_auth instead of a post.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from automations.override_bulletin import dd_search as S
from automations.shared import run_manifest


def setUpModule():
    os.environ["SLACK_USER_TOKEN"] = "xoxp-not-a-real-token-for-tests"


class AccumulateManifestTest(unittest.TestCase):

    def setUp(self):
        self.calls = []

        def fake(report_id, **kw):
            self.calls.append((report_id, kw))
            return None

        self._patch = mock.patch.object(run_manifest, "write_manifest", fake)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _kw(self):
        self.assertEqual(len(self.calls), 1)
        return self.calls[0][1]

    def test_a_clean_run_files_every_row_as_succeeded(self):
        S._write_accumulate_manifest(
            "9.6.26", ["Karrington Moody", "Justin Fermin",
                       "Marcos Barbosa", "Milan Godbolt"], [])
        self.assertEqual(self.calls[0][0], "dd_special_accumulate")
        kw = self._kw()
        self.assertEqual(kw["failed"], [])
        self.assertEqual(len(kw["succeeded"]), 4)
        self.assertEqual(kw["retry_args"], ["--accumulate", "--write"])
        self.assertIn("9.6.26", kw["note"])

    def test_a_row_that_could_not_be_placed_is_a_recorded_failure(self):
        """A name with no row, or a tab that has not rolled yet, leaves a cell
        BLANK — the shape that publishes a short bulletin."""
        S._write_accumulate_manifest("9.6.26", ["Karrington Moody"],
                                     ["Justin Fermin"])
        kw = self._kw()
        self.assertEqual(kw["failed"], ["Justin Fermin"])
        self.assertEqual(kw["succeeded"], ["Karrington Moody"])
        self.assertIn("Justin Fermin", kw["note"])

    def test_writing_nothing_is_a_failed_run_not_an_empty_one(self):
        S._write_accumulate_manifest("9.6.26", [],
                                     ["Karrington Moody", "Justin Fermin"])
        kw = self._kw()
        self.assertEqual(len(kw["failed"]), 2)
        self.assertEqual(kw["succeeded"], [])

    def test_a_manifest_that_cannot_be_written_never_raises(self):
        """Cells are already on the tab by then — a bookkeeping failure must not
        turn a good write into a crash."""
        def boom(*a, **k):
            raise RuntimeError("disk full")

        with mock.patch.object(run_manifest, "write_manifest", boom):
            S._write_accumulate_manifest("9.6.26", ["Karrington Moody"], [])


if __name__ == "__main__":
    unittest.main()
