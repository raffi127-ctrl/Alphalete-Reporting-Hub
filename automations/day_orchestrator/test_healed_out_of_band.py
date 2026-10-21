"""An INCOMPLETE report fixed by a re-run outside the loop must not alert.

2026-10-21: daily_focus went INCOMPLETE at 04:54 (German Lopez x2 + JR Young).
A queued `lucy rerun daily_focus --retry-inaccessible` filled all three and
closed the ticket at 07:35 — and rewrote the manifest clean, dropping its
retry_args. At 07:37 the alert sweep read "no retry left" off that clean
manifest and posted a NEW "3 didn't fill" ticket from its stale 04:54 status.

Run:  python -m unittest automations.day_orchestrator.test_healed_out_of_band
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from automations.day_orchestrator import run as R
from automations.day_orchestrator import state

MANIFEST_R = SimpleNamespace(verify={"type": "manifest", "report_id": "daily-focus"})


def _rs(last="2026-10-21T04:54:55"):
    return state.ReportState(report_id="daily_focus", status=state.INCOMPLETE,
                             last_attempt_ts=last,
                             missing=["GERMAN LOPEZ", "German Lopez",
                                      "John Richard Young"])


def _manifest(**kw):
    m = {"report_id": "daily-focus", "run_ts": "2026-10-21T07:35:35",
         "ok": True, "failed": [], "retry_args": []}
    m.update(kw)
    return mock.patch("automations.shared.run_manifest.read_manifest",
                      return_value=m)


class HealedOutOfBandTest(unittest.TestCase):
    def test_clean_manifest_after_our_attempt_is_healed(self):
        with _manifest():
            self.assertTrue(R._healed_out_of_band(_rs(), MANIFEST_R))

    def test_still_failing_manifest_is_not_healed(self):
        with _manifest(ok=False, failed=["John Richard Young"]):
            self.assertFalse(R._healed_out_of_band(_rs(), MANIFEST_R))

    def test_clean_manifest_older_than_our_attempt_proves_nothing(self):
        with _manifest(run_ts="2026-10-21T04:10:00"):
            self.assertFalse(R._healed_out_of_band(_rs(), MANIFEST_R))

    def test_non_manifest_verify_is_never_healed_this_way(self):
        r = SimpleNamespace(verify={"type": "sheet_cells"})
        with _manifest():
            self.assertFalse(R._healed_out_of_band(_rs(), r))

    def test_sweep_marks_done_and_sends_no_alert(self):
        ds = state.DayState(date="2026-10-21")
        ds.reports["daily_focus"] = _rs()
        with _manifest(), \
                mock.patch.object(R, "_maybe_failure_alert") as alert, \
                mock.patch.object(state, "save"):
            R._alert_new_failures({}, ds, {"daily_focus": MANIFEST_R},
                                  channel=None, dry_run=True)
        alert.assert_not_called()
        self.assertEqual(ds.reports["daily_focus"].status, state.DONE)

    def test_without_the_heal_it_still_alerts(self):
        ds = state.DayState(date="2026-10-21")
        ds.reports["daily_focus"] = _rs()
        with _manifest(ok=False, failed=["John Richard Young"]), \
                mock.patch.object(R, "_retryable_incomplete", return_value=False), \
                mock.patch.object(R, "_alert_on_hold", return_value=False), \
                mock.patch.object(R, "_maybe_failure_alert") as alert:
            R._alert_new_failures({}, ds, {"daily_focus": MANIFEST_R},
                                  channel=None, dry_run=True)
        alert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
