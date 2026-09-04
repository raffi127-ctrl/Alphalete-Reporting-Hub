"""A rerun that delivered NOTHING must not close an incident.

2026-09-01: a DRY run of box_order_log_tier_backfill exited 0, and the ✅ that
follows a clean run closed `drop-box-order-log` at 08:05 — thirteen minutes
before the board it was testing reached the thread. Anyone reading the channel
in between saw a RESOLVED ticket over a thread still missing its image.

    python -m unittest automations.day_orchestrator.test_probe_reason -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from automations.day_orchestrator import mini_control
from automations.day_orchestrator.mini_control import _probe_reason

CONFIG = (Path(__file__).resolve().parent / "schedule_config.json")


class ProbeReason(unittest.TestCase):
    def test_dry_by_default_handle_without_its_flag_is_a_probe(self):
        gate = {"delivers_only_with": "--post"}
        self.assertEqual(_probe_reason(gate, []), "no --post")
        self.assertEqual(_probe_reason(gate, ["--channel", "C0"]), "no --post")

    def test_same_handle_WITH_the_flag_really_ran(self):
        gate = {"delivers_only_with": "--post"}
        self.assertEqual(_probe_reason(gate, ["--post"]), "")

    def test_explicit_probe_flags(self):
        for flag in ("--dry-run", "--dry", "--check", "--inspect"):
            self.assertEqual(_probe_reason({}, [flag]), flag)

    def test_an_ordinary_rerun_is_unchanged(self):
        # The whole point: every report that isn't a dry-by-default handle keeps
        # closing its incident exactly as before.
        self.assertEqual(_probe_reason({}, []), "")
        self.assertEqual(_probe_reason({}, ["--only", "churn"]), "")
        self.assertEqual(_probe_reason(None, []), "")

    def test_the_two_BOX_repair_handles_carry_the_gate(self):
        # They say "DRY by default; --post does the work" in their own
        # docstrings; the config is where the rerun path can read it.
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))["reports"]
        for rid in ("box_order_log_tier_backfill", "box_order_log_repost"):
            self.assertEqual(raw[rid].get("delivers_only_with"), "--post", rid)


class _FakeHubPublish:
    """Stands in for day_orchestrator.hub_publish inside _publish_rerun_done."""

    def __init__(self):
        self.kwargs = None

    def final_status(self, report_id, ok):
        return "success" if ok else "failed"

    def publish_done(self, report_id, display_name, **kw):
        self.kwargs = kw
        return True


class ProbePublish(unittest.TestCase):
    """A probe is silent in BOTH directions — it can neither close an incident
    nor open one. 2026-09-03: a `--dry-run` of owners_metrics_churn timed out on
    a Tableau locator and posted "closed a run with status FAILED" to
    #claudecorrections nine minutes after the real run had been resolved."""

    def _publish(self, ok, probe):
        """Install the fake on BOTH resolution paths.

        THE BUG THIS FIXES (2026-09-04). `_publish_rerun_done` does
        `from automations.day_orchestrator import hub_publish`, and once ANYTHING
        in the process has genuinely imported that submodule, the import resolves
        through the PACKAGE ATTRIBUTE, not sys.modules. So a sys.modules-only
        swap held when this file ran alone and was silently bypassed in a
        full-suite run — the REAL publish_done ran with report_id `r`, status
        failed, alert_on_fail True. It posted a live 🚨, opened the incident
        "R failed" that sat in #claudecorrections for a day pointing at a report
        that does not exist, appended a Hub activity row stamped
        MacBook-Pro-3.local, and auto-created a phantom library card `r`.

        Same trap, same cure, as automations/b2b_metrics/test_manifest_merge
        `_stubbed`. A stub that degrades to production is not a stub."""
        from unittest import mock

        import automations.day_orchestrator as _pkg
        fake = _FakeHubPublish()
        with mock.patch.dict(
                sys.modules,
                {"automations.day_orchestrator.hub_publish": fake}), \
             mock.patch.object(_pkg, "hub_publish", fake, create=True):
            # create=True because BOTH orders have to work: run this file alone
            # and the package has no such attribute yet (the sys.modules entry is
            # what bites); run the whole suite and it does.
            mini_control._publish_rerun_done("r", "R", ok, "run-1", probe)
        self.assertIsNotNone(
            fake.kwargs,
            "the stub was bypassed — the REAL hub_publish just ran, which is "
            "how the 'R failed' incident reached #claudecorrections")
        return fake.kwargs

    def test_failing_probe_opens_no_incident(self):
        kw = self._publish(ok=False, probe="--dry-run")
        self.assertEqual(kw["status"], "failed")      # the Hub pill still goes red
        self.assertFalse(kw["alert_on_fail"])         # …but the channel stays quiet

    def test_clean_probe_still_closes_nothing(self):
        kw = self._publish(ok=True, probe="--dry-run")
        self.assertFalse(kw["clear_failure"])

    def test_a_real_rerun_still_alerts_and_still_closes(self):
        kw = self._publish(ok=False, probe="")
        self.assertTrue(kw["alert_on_fail"])
        kw = self._publish(ok=True, probe="")
        self.assertTrue(kw["clear_failure"])


if __name__ == "__main__":
    unittest.main()
