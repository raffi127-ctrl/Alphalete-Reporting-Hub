"""A rerun that delivered NOTHING must not close an incident.

2026-09-01: a DRY run of box_order_log_tier_backfill exited 0, and the ✅ that
follows a clean run closed `drop-box-order-log` at 08:05 — thirteen minutes
before the board it was testing reached the thread. Anyone reading the channel
in between saw a RESOLVED ticket over a thread still missing its image.

    python -m unittest automations.day_orchestrator.test_probe_reason -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
