"""A report we PAUSED on purpose must not page the channel for not running.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.machine_digest.test_paused_not_watched

WHAT THIS GUARDS (2026-09-07). Texas de Brazil was paused on Sat 9/5 — the
competition ended, the wrapper was flagged off and its LaunchAgent booted out.
At 10:10 on Mon 9/7 the corrections channel got
`standalone-june_texas_de_brazil_monthly_competition` — "didn't run today on the
mini" — for the job we had switched off ourselves two days earlier.

WHY it happened, and why a declaration alone did not stop it: this watcher's
"didn't run" branch learns from HISTORY (`_historical_expected`, three weeks of
same-weekday rows), not from schedule_config. So pausing a report that HAD been
running daily is precisely what makes it start looking missing. The stand-down
was declared in dashboard.py, which no watcher can import (Streamlit), so the
Hub greyed the pill while the watcher went on expecting the run.

THE TWO THINGS THIS PINS:
  1. The declaration is SHARED — day_orchestrator.paused_reports, importable
     with no Streamlit, read by the Hub AND by this watcher.
  2. `skip`, not `offday` — same reasoning as _retired_ids / _not_armed_ids:
     offday suppresses only the "didn't run" guess and still reports a FAILED,
     which is right for a live report on its day off and wrong for one nobody
     expects to run at all.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.day_orchestrator import paused_reports
from automations.machine_digest import run as md


class PausedIdsTest(unittest.TestCase):
    def test_paused_ids_reads_the_shared_declaration(self):
        self.assertEqual(md._paused_ids(), set(paused_reports.PAUSED_REPORTS))

    def test_texas_de_brazil_is_skipped_under_both_spellings(self):
        # The Activity log writes the LIBRARY id; schedule_config and `lucy
        # rerun` use the short key. Matching one only is how a skip set silently
        # does nothing — the bug _orchestrator_ids records for sci_campaigns.
        ids = md._paused_ids()
        self.assertIn("june_texas_de_brazil_monthly_competition", ids)
        self.assertIn("texas_de_brazil", ids)

    def test_unreadable_declaration_alerts_as_before(self):
        # A paused report alerting is a nuisance; a live one going quiet is the
        # bug this watcher exists to catch. So a broken import must skip
        # NOTHING, never everything.
        with mock.patch.object(paused_reports, "paused_ids",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(md._paused_ids(), set())

    def test_a_live_report_is_not_skipped(self):
        self.assertNotIn("recruiting", md._paused_ids())


if __name__ == "__main__":
    unittest.main()
