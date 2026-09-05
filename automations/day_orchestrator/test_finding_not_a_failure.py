"""A findings AUDIT must never be paged as a FAILED report.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_finding_not_a_failure

WHAT THIS GUARDS (2026-09-05). vantura_board_audit ran perfectly at 04:01,
found 17 board data-quality findings, exited 0 and wrote the manifest it
deliberately writes for that case — `ok=False, kind='finding'`, with the
findings in `failed` and nothing in `succeeded`. Its own finding post said, in
so many words, "the run itself was fine". Four seconds later the channel got a
SECOND, red ticket for the same run:

    :x: Vantura Board Audit (daily data quality) failed
    `vantura-board-audit` closed a run with status **FAILED**

Two things had to line up:

  1. `run_manifest.outcome` treats `failed` without `succeeded` as a total
     failure. That is the right default for a report that broke, but a
     kind='finding' manifest is not a broken report — `ok=False` there means
     "it worked and it found things", which is orange, not red.
  2. `run.py`'s INCOMPLETE publish_done was the ONE call site of the three in
     that file that let `alert_on_fail` default to True, so the status went
     straight on to fire hub_publish._alert_failure — the page the orchestrator
     is supposed to own, and already sends its own version of.

Either one alone re-creates the false alarm, so both are pinned here.
"""
from __future__ import annotations

import datetime as dt
import inspect
import re
import unittest
from unittest import mock

from automations.day_orchestrator import hub_publish
from automations.shared import run_manifest


def _manifest(**over):
    m = {"report_id": "vantura-board-audit",
         "run_ts": dt.datetime.now().isoformat(timespec="seconds"),
         "ok": False, "kind": "finding",
         "failed": ["ROLL CALL STALE: 'Edwin Garcia' …"],
         "succeeded": []}
    m.update(over)
    return m


class FindingManifestIsOrangeNotRed(unittest.TestCase):
    def _resolve(self, m):
        with mock.patch.object(run_manifest, "read_manifest", return_value=m):
            return run_manifest.outcome("vantura-board-audit")

    def test_findings_are_partial(self):
        self.assertEqual(self._resolve(_manifest()), "partial")

    def test_incomplete_status_is_partial_too(self):
        """The pill the orchestrator actually publishes."""
        with mock.patch.object(run_manifest, "read_manifest",
                               return_value=_manifest()):
            self.assertEqual(
                hub_publish.incomplete_status("vantura-board-audit"), "partial")

    def test_a_clean_audit_is_still_success(self):
        self.assertEqual(self._resolve(_manifest(ok=True, failed=[])),
                         "success")

    def test_a_real_break_is_still_failed(self):
        """The conservative default has to survive for ordinary reports: a
        non-finding manifest with failed parts and no successes stays RED."""
        self.assertEqual(
            self._resolve(_manifest(kind="part", failed=["carlos: churn_air"])),
            "failed")

    def test_a_partial_run_is_still_partial(self):
        self.assertEqual(
            self._resolve(_manifest(kind="part", failed=["a"],
                                    succeeded=["b"])),
            "partial")

    def test_yesterdays_finding_does_not_colour_today(self):
        old = _manifest(run_ts=(dt.datetime.now()
                                - dt.timedelta(days=1)).isoformat())
        self.assertIsNone(self._resolve(old))


class OrchestratorNeverDoublePages(unittest.TestCase):
    """Any publish_done in run.py that can close a run NON-green has to opt out
    of hub_publish's failure alert — the orchestrator sends its own summary, and
    a second witness for one run is the duplicate-post problem incident_thread
    exists to stop.

    Scoped to the calls that pass an explicit `status=`. The other two in that
    file are RECOVERY publishes (INCOMPLETE→DONE, FAILED→DONE on re-verify) that
    take the default 'success', and _alert_failure only ever fires on 'failed',
    so they cannot page anyone."""

    def test_status_bearing_publish_done_calls_opt_out_of_the_alert(self):
        from automations.day_orchestrator import run as orch
        src = inspect.getsource(orch)
        calls = re.findall(r"hub_publish\.publish_done\((?:[^()]|\([^()]*\))*\)",
                           src)
        self.assertGreaterEqual(len(calls), 3, "call sites moved — re-read this")
        risky = [c for c in calls if "status=" in c]
        self.assertGreaterEqual(len(risky), 3, "status= call sites moved")
        missing = [c for c in risky if "alert_on_fail=False" not in c]
        self.assertEqual(
            missing, [],
            "publish_done without alert_on_fail=False fires hub_publish."
            "_alert_failure on top of the orchestrator's own summary:\n"
            + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
