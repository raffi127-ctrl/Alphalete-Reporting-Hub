"""A scoped (--only) re-run has to be able to CLOSE the day out.

Regression cover for 2026-08-25: churn dropped one of its 8 images at 04:42, the
repair re-ran `--only churn` — and daily_metrics deliberately skipped the manifest
on a scoped run, so the manifest kept naming churn as missing. The orchestrator
kept verifying INCOMPLETE, kept asking for the same re-run, and each one posted
all 8 churn images again: 16 duplicate charts in #alphalete-sales.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from automations.daily_metrics import run as dm
from automations.shared import repair_hint, run_manifest as rm

CHURN = "🌐 New Internet Churn + 📊 Wireless Churn"
SALES = "📅 Sales Scheduled 6+ Days Out"


def _sel(*slugs):
    return [m for m in dm.METRICS if m[0] in slugs]


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        # Manifests + repair hints land in the temp dir, never the real output/.
        for mod, attr, val in ((rm, "MANIFEST_DIR", tmp / "manifests"),
                               (repair_hint, "HINT_DIR", tmp / "hints")):
            patcher = mock.patch.object(mod, attr, val)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Nothing in a test may reach Slack or the shared office checklist.
        sda = types.ModuleType("automations.shared.section_drop_alert")
        self.alerts, self.resolves = [], []
        sda.alert = lambda **kw: self.alerts.append(kw)
        sda.resolved = lambda rid, **kw: self.resolves.append(rid)
        omr = types.ModuleType("automations.office_metrics.runner")
        omr.MAIN_OFFICE_LABEL, omr.MAIN_OFFICE_CHANNEL = "Local Office", "C1"
        self.rows = []
        omr.record_status = lambda label, ch, **kw: self.rows.append(kw)
        for name, mod in (("automations.shared.section_drop_alert", sda),
                          ("automations.office_metrics.runner", omr)):
            patcher = mock.patch.dict(sys.modules, {name: mod})
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def manifest(self):
        return rm.read_manifest("daily_metrics")


class FullRun(_Base):
    def test_records_the_failed_metric(self):
        dm._record_outcome(dm.METRICS, [CHURN], scoped=False)
        m = self.manifest()
        self.assertEqual(m["failed"], [CHURN])
        self.assertFalse(m["ok"])
        self.assertEqual(m["retry_args"], ["--only", "churn"])
        self.assertIn(f"{len(dm.METRICS) - 1}/{len(dm.METRICS)}", m["note"])
        self.assertEqual(self.rows[-1]["ok"], False)

    def test_clean_run_records_clean(self):
        dm._record_outcome(dm.METRICS, [], scoped=False)
        m = self.manifest()
        self.assertTrue(m["ok"])
        self.assertEqual(m["failed"], [])
        self.assertEqual(self.rows[-1]["ok"], True)


class ScopedRerun(_Base):
    def test_successful_rerun_clears_the_metric_and_closes_the_alert(self):
        dm._record_outcome(dm.METRICS, [CHURN], scoped=False)
        dm._record_outcome(_sel("churn"), [], scoped=True)
        m = self.manifest()
        self.assertEqual(m["failed"], [])       # THE bug: this stayed [CHURN]
        self.assertTrue(m["ok"])
        self.assertEqual(m["retry_args"], [])
        self.assertIsNone(m["remediation"])
        self.assertEqual(self.resolves, ["daily_metrics"])   # thread closed
        self.assertEqual(self.rows[-1]["ok"], True)          # office row green

    def test_rerun_does_not_speak_for_the_metrics_it_did_not_run(self):
        dm._record_outcome(dm.METRICS, [CHURN, SALES], scoped=False)
        dm._record_outcome(_sel("churn"), [], scoped=True)
        m = self.manifest()
        self.assertEqual(m["failed"], [SALES])
        self.assertFalse(m["ok"])
        self.assertEqual(m["retry_args"], ["--only", "sales_6plus"])

    def test_rerun_that_fails_again_keeps_the_metric_failed(self):
        dm._record_outcome(dm.METRICS, [CHURN], scoped=False)
        dm._record_outcome(_sel("churn"), [CHURN], scoped=True)
        self.assertEqual(self.manifest()["failed"], [CHURN])

    def test_no_manifest_from_today_is_left_alone(self):
        # The full run never reached its summary; one metric can't vouch for ten.
        dm._record_outcome(_sel("churn"), [], scoped=True)
        self.assertIsNone(self.manifest())
        self.assertEqual(self.rows, [])

    def test_yesterdays_manifest_is_not_merged_into(self):
        rm.write_manifest("daily_metrics", failed=[CHURN],
                          run_ts=dt.datetime.now() - dt.timedelta(days=1))
        dm._record_outcome(_sel("churn"), [], scoped=True)
        self.assertEqual(self.manifest()["failed"], [CHURN])  # untouched


class ScopedRepairCommand(_Base):
    """One dropped image should be re-posted on its own — not by re-running the
    metric, which re-posts the 7 that already landed."""

    def test_lone_failure_with_a_hint_uses_the_module_args_hatch(self):
        repair_hint.write("churn", missed=["Wireless Churn 90-day"],
                          module_args="--only wireless --only-period 90")
        dm._record_outcome(dm.METRICS, [CHURN], scoped=False)
        m = self.manifest()
        self.assertEqual(m["retry_args"],
                         ["--only", "churn", "--module-args",
                          "--only wireless --only-period 90"])
        self.assertIn("--module-args", m["remediation"]["fix"])
        self.assertIn("Wireless Churn 90-day", m["remediation"]["message"])

    def test_hint_without_module_args_falls_back_to_the_whole_metric(self):
        # Two images down can't be expressed as one scoped command.
        repair_hint.write("churn", missed=["A", "B"], module_args=None)
        dm._record_outcome(dm.METRICS, [CHURN], scoped=False)
        self.assertEqual(self.manifest()["retry_args"], ["--only", "churn"])

    def test_hint_is_ignored_when_another_metric_also_failed(self):
        # --module-args needs exactly one --only slug.
        repair_hint.write("churn", missed=["Wireless Churn 90-day"],
                          module_args="--only wireless --only-period 90")
        dm._record_outcome(dm.METRICS, [CHURN, SALES], scoped=False)
        self.assertEqual(self.manifest()["retry_args"],
                         ["--only", "churn,sales_6plus"])


class RepairHint(_Base):
    def test_round_trip(self):
        repair_hint.write("churn", missed=["x"], module_args="--only wireless")
        self.assertEqual(repair_hint.read("churn")["module_args"],
                         "--only wireless")

    def test_yesterdays_hint_is_never_read_back(self):
        # A repair command for yesterday would post into yesterday's thread.
        repair_hint.write("churn", missed=["x"], module_args="--only wireless",
                          day=dt.date.today() - dt.timedelta(days=1))
        self.assertIsNone(repair_hint.read("churn"))

    def test_clear_removes_it_and_is_safe_when_absent(self):
        repair_hint.write("churn", missed=["x"])
        repair_hint.clear("churn")
        repair_hint.clear("churn")
        self.assertIsNone(repair_hint.read("churn"))


if __name__ == "__main__":
    unittest.main()
