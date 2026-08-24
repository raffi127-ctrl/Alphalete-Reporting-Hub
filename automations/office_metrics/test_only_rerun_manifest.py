"""`runner._merge_only_rerun` — an --only re-run correcting TODAY's manifest.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.office_metrics.test_only_rerun_manifest

WHAT THIS GUARDS (Eve 2026-08-24, rashad_metrics churn). The orchestrator's
auto-retry runs the manifest's own retry_args, which are always
`--only <failed slugs>` — and an --only run used to write no manifest at all. So
the retry could never clear the flag it was retrying: churn re-ran, posted all
eight boards, and reconcile re-read the same untouched manifest, kept the report
INCOMPLETE and fired "8/9 metrics posted … failed: churn" over a log tail whose
last line was "All wired metrics ok". Every recovered flake cried wolf.

The merge must:
  • clear the office when the retried metric lands (failed=[] → the alert thread
    closes itself and reconcile can reach DONE);
  • leave every metric it did NOT run exactly as the full run judged it;
  • re-scope retry_args to what is still missing;
  • write NOTHING when there is no verdict from today to correct — a partial run
    must never invent an office-wide verdict;
  • sit out a BLOCKED-CHANNEL verdict, whose own remediation says the fix is a
    Slack invite, not a re-run.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.office_metrics import runner
from automations.office_metrics import offices as _off
from automations.shared import run_manifest as _rm

OFFICE = "rashad"
TODAY = dt.date.today().isoformat() + "T04:12:00"


class MergeOnlyRerunTest(unittest.TestCase):
    def setUp(self):
        self.o = _off.get(OFFICE)
        self.full = runner.metrics_for(self.o)
        self.churn = next(m for m in self.full if m["slug"] == "churn")
        self.others = [m["label"] for m in self.full if m["slug"] != "churn"]
        self.written = []
        self.store = {}
        self._real = (_rm.read_manifest, _rm.write_manifest,
                      runner._record_office_status)
        _rm.read_manifest = lambda rid: self.store.get(rid)
        _rm.write_manifest = lambda rid, **kw: self.written.append(("m", kw))
        runner._record_office_status = lambda o, **kw: self.written.append(("s", kw))

    def tearDown(self):
        (_rm.read_manifest, _rm.write_manifest,
         runner._record_office_status) = self._real

    def _base(self, **over):
        m = {"run_ts": TODAY, "ok": False, "failed": [self.churn["label"]],
             "succeeded": list(self.others)}
        m.update(over)
        return m

    def _rerun(self, manifest, results, blocked=()):
        self.store.clear()
        if manifest:
            self.store[self.o.report_id] = manifest
        return runner._merge_only_rerun(self.o, results, self.full, list(blocked),
                                        dest_desc=self.o.channel_name,
                                        blocked_note="")

    def _manifest(self):
        return next(kw for kind, kw in self.written if kind == "m")

    def _status(self):
        return next(kw for kind, kw in self.written if kind == "s")

    def test_recovered_metric_clears_the_office(self):
        """The whole point: churn lands on the retry, so nothing is failing."""
        self.assertTrue(self._rerun(
            self._base(),
            [(self.o.channel_name, "churn", self.churn["label"], True, "74s")]))
        m = self._manifest()
        self.assertEqual(m["failed"], [])
        self.assertEqual(sorted(m["succeeded"]),
                         sorted(self.others + [self.churn["label"]]))
        self.assertNotIn("--only", m["retry_args"])
        self.assertTrue(self._status()["ok"])

    def test_still_failing_stays_failed_and_keeps_its_scope(self):
        self.assertTrue(self._rerun(
            self._base(),
            [(self.o.channel_name, "churn", self.churn["label"], False, "exit 1")]))
        m = self._manifest()
        self.assertEqual(m["failed"], [self.churn["label"]])
        self.assertEqual(m["retry_args"][-2:], ["--only", "churn"])
        self.assertFalse(self._status()["ok"])

    def test_metrics_it_did_not_run_are_left_alone(self):
        """Two missed; the retry recovers one. The other must stay named."""
        first = self.full[0]
        self.assertTrue(self._rerun(
            self._base(failed=[self.churn["label"], first["label"]],
                       succeeded=[l for l in self.others if l != first["label"]]),
            [(self.o.channel_name, "churn", self.churn["label"], True, "70s")]))
        m = self._manifest()
        self.assertEqual(m["failed"], [first["label"]])
        self.assertEqual(m["retry_args"][-2:], ["--only", first["slug"]])

    def test_no_manifest_writes_nothing(self):
        self.assertFalse(self._rerun(
            None,
            [(self.o.channel_name, "churn", self.churn["label"], True, "74s")]))
        self.assertEqual(self.written, [])

    def test_yesterdays_verdict_is_not_revived(self):
        self.assertFalse(self._rerun(
            self._base(run_ts="2026-08-23T04:00:00"),
            [(self.o.channel_name, "churn", self.churn["label"], True, "74s")]))
        self.assertEqual(self.written, [])

    def test_a_blocked_channel_verdict_is_left_to_the_invite(self):
        self.assertFalse(self._rerun(
            self._base(remediation={"reason": "not_in_channel", "fix": "invite"}),
            [(self.o.channel_name, "churn", self.churn["label"], True, "74s")]))
        self.assertEqual(self.written, [])

    def test_a_rerun_that_itself_hits_a_block_writes_nothing(self):
        self.assertFalse(self._rerun(
            self._base(),
            [(self.o.channel_name, "churn", self.churn["label"], False,
              "channel unreachable: not_in_channel")],
            blocked=[(self.o.channel_name, "C1", "not_in_channel")]))
        self.assertEqual(self.written, [])


if __name__ == "__main__":
    unittest.main()
