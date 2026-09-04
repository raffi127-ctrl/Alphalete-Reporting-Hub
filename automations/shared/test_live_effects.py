"""A unit test must not be able to reach Slack, an incident, or the Hub library.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_live_effects

WHAT THIS GUARDS (2026-09-04). #claudecorrections-and-requests carried an
incident "R failed" — report_id `r`, machine MacBook-Pro-3.local — open for a
day, with Lucy noting that retries had not fixed it and re-running would not
either. Correct: there is no report `r`. It is the fixture on line 77 of
automations/day_orchestrator/test_probe_reason.py, whose sys.modules-only stub of
hub_publish is bypassed whenever the package attribute already exists — so the
REAL publish_done ran with status failed and alert_on_fail True.

That test is fixed. This is the second lock under it, because the first one
depends on every future test author knowing about an import subtlety, and this
one does not.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import hub_coverage, hub_publish
from automations.shared import live_effects

REPO_ROOT = Path(__file__).resolve().parents[2]


class TheDetectorItself(unittest.TestCase):

    def test_it_sees_the_test_runner_driving_it(self):
        self.assertTrue(live_effects.driven_by_a_test())

    def test_it_is_false_in_a_plain_process(self):
        """The half that cannot be asserted from inside a test — so ask a
        subprocess with no runner on its stack. A false positive here would
        silence a REAL 4am failure alert, which is worse than the bug."""
        out = subprocess.run(
            [sys.executable, "-c",
             "from automations.shared import live_effects;"
             "print(live_effects.driven_by_a_test())"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), "False", out.stderr[-400:])

    def test_importing_unittest_is_not_enough(self):
        """It walks FRAMES, not sys.modules — a report that imports unittest
        transitively must still be able to alert."""
        out = subprocess.run(
            [sys.executable, "-c",
             "import unittest;"
             "from automations.shared import live_effects;"
             "print(live_effects.driven_by_a_test())"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), "False", out.stderr[-400:])


class NoAlertReachesSlackFromATest(unittest.TestCase):
    """THE ONE THAT COST A DAY."""

    def test_alert_failure_posts_nothing(self):
        posted = []
        fake_notify = mock.Mock()
        fake_notify.post_alert = lambda *a, **k: posted.append((a, k))
        with mock.patch.dict(
                sys.modules, {"automations.day_orchestrator.notify": fake_notify}):
            hub_publish._alert_failure("r", "R")
        self.assertEqual(posted, [], "a test just posted to #claudecorrections")

    def test_clear_failure_closes_nobodys_incident(self):
        """Worse than a stray alert: this ✅s an OPEN ticket for a real problem
        that nobody fixed."""
        resolved = []
        fake_inc = mock.Mock()
        fake_inc.resolve_report = lambda *a, **k: resolved.append((a, k))
        with mock.patch.dict(
                sys.modules, {"automations.shared.incident_thread": fake_inc}):
            hub_publish._clear_failure("r", "R")
        self.assertEqual(resolved, [], "a test just resolved a live incident")


class NoPhantomHubCardFromATest(unittest.TestCase):

    def test_resolve_card_creates_nothing(self):
        created = []
        with mock.patch.object(
                hub_coverage, "ensure_library_card",
                lambda *a, **k: created.append((a, k)) or (True, "")):
            got = hub_coverage.resolve_card("r", "R", _existing=set())
        self.assertEqual(created, [], "a test just minted a Hub library card")

    def test_the_id_still_resolves_so_callers_are_unchanged(self):
        """Only the WRITE is refused. A caller that logs the run against the
        resolved id keeps working — the guard must not turn into a crash."""
        with mock.patch.object(hub_coverage, "ensure_library_card",
                               lambda *a, **k: (True, "")):
            self.assertEqual(
                hub_coverage.resolve_card("r", "R", _existing=set()), "r")


if __name__ == "__main__":
    unittest.main()
