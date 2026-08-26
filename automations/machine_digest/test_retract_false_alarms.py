"""The watcher taking back a "didn't run today" it should never have posted.

The dangerous half is NOT the retraction — it's that `standalone-<id>` is the
incident key for EVERY standalone alert kind, so a retraction that keys only on
"this report is exempt from the didn't-run check" would close a REAL failure
thread for a hand-run-only report. Being un-scheduled was never a reason to stop
watching for failures. Most of these tests exist to pin that down.
"""
import datetime as dt
import unittest
from unittest import mock

from automations.machine_digest import run as md

DAY = dt.date(2026, 8, 26)

MISSED = ("*Alphalete Org 1on1s — B2B OPT only* — didn't run today on Lucy 2"
          "\n\n_incident · standalone-alphalete_org_b2b · open 2026-08-24_")
FAILED = ("*Alphalete Org 1on1s — B2B OPT only* — failed"
          "\n\n_incident · standalone-alphalete_org_b2b · open 2026-08-24_")


class Retract(unittest.TestCase):

    def _run(self, *, open_keys, parent_text, structural=(), offday=(),
             index=None, dry_run=False):
        self.resolved = []

        def _resolve(*, key, lines, channel, dry_run=False):
            self.resolved.append((key, "\n".join(lines)))
            return True

        inc = mock.MagicMock()
        inc.open_keys.return_value = list(open_keys)
        inc._load_index.return_value = index or {}
        inc._find_any_state.return_value = {"text": parent_text}
        inc.resolve.side_effect = _resolve
        notify = mock.MagicMock()
        notify._corrections_channel.return_value = "C1"

        with mock.patch.dict("sys.modules", {
                "automations.shared.incident_thread": inc,
                "automations.day_orchestrator.notify": notify}), \
             mock.patch.object(md, "_handrun_only_ids", return_value=set(structural)), \
             mock.patch.object(md, "_oneshot_utility_ids", return_value=set()), \
             mock.patch.object(md, "_offday_standalone_ids", return_value=set(offday)):
            return md._retract_false_alarms(object(), DAY, dry_run, "ts")

    # ---- the guard that matters -------------------------------------------

    def test_a_real_failure_on_an_exempt_report_is_NEVER_retracted(self):
        """The report is hand-run-only AND its thread is open — but the thread
        is about a FAILURE. The failure is still true."""
        n = self._run(open_keys=["standalone-alphalete_org_b2b"],
                      parent_text=FAILED,
                      structural=["alphalete_org_b2b"])
        self.assertEqual(n, 0)
        self.assertEqual(self.resolved, [])

    def test_an_unreadable_parent_is_left_alone(self):
        n = self._run(open_keys=["standalone-alphalete_org_b2b"],
                      parent_text="", structural=["alphalete_org_b2b"])
        self.assertEqual(n, 0)

    def test_failure_and_drop_keys_are_never_considered(self):
        for key in ("failure-alphalete_org_b2b", "drop-alphalete_org_b2b",
                    "nonew-bg_check_sync"):
            n = self._run(open_keys=[key], parent_text=MISSED,
                          structural=["alphalete_org_b2b", "bg_check_sync"])
            self.assertEqual(n, 0, key)

    # ---- the retraction itself --------------------------------------------

    def test_hand_run_only_didnt_run_is_retracted(self):
        n = self._run(open_keys=["standalone-alphalete_org_b2b"],
                      parent_text=MISSED, structural=["alphalete_org_b2b"])
        self.assertEqual(n, 1)
        key, body = self.resolved[0]
        self.assertEqual(key, "standalone-alphalete_org_b2b")
        self.assertIn("Retracted", body)
        self.assertIn("by hand", body)
        self.assertIn("nothing needs re-running", body)

    def test_a_report_with_no_exemption_is_untouched(self):
        n = self._run(open_keys=["standalone-something_real"],
                      parent_text=MISSED)
        self.assertEqual(n, 0)

    # ---- off-day is asked against the day the alert was RAISED -------------

    def test_offday_uses_the_incidents_own_opened_date(self):
        """Today's off-day list can't answer for an alert raised last Sunday."""
        n = self._run(open_keys=["standalone-b2b_dispositions"],
                      parent_text=MISSED, offday=["b2b_dispositions"],
                      index={"standalone-b2b_dispositions": {"opened": "2026-08-23"}})
        self.assertEqual(n, 1)
        self.assertIn("Sunday", self.resolved[0][1])

    def test_an_undatable_offday_candidate_is_skipped(self):
        n = self._run(open_keys=["standalone-b2b_dispositions"],
                      parent_text=MISSED, offday=["b2b_dispositions"], index={})
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
