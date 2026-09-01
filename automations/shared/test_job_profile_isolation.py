"""Concurrent reports must not share one Chrome profile.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_job_profile_isolation

WHY (2026-09-01). Every browser report defaulted to the same .browser_profile.
Chrome's singleton means concurrent runs EVICT each other: the survivor keeps
the profile and the loser's context dies mid-run as TargetClosedError. Lucy 1
routinely runs four patchright drivers at once (orchestrator pass + standalone
LaunchAgents + reruns), so this was a standing collision.

Measured at 08:56 that morning: 4 drivers, 8 Chromes on .browser_profile, and
org_sales_board losing its delta boxes to "Download.save_as: Target page,
context or browser has been closed" — in an hour with ZERO Chrome crash
reports. The Chrome-152 crash wave had already passed; this was pure contention,
and it looked identical to the crash because both raise TargetClosedError.

The remedy was already in the file twice as a per-job escape hatch (Owner
Showdown 2026-08-03, other_office_knocks 2026-08-18). This makes it the default.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import os
import unittest

from automations.shared import tableau_patchright as tp


class JobProfileIsolationTest(unittest.TestCase):

    def setUp(self):
        self._prev = os.environ.get("HUB_REPORT_ID")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._prev is None:
            os.environ.pop("HUB_REPORT_ID", None)
        else:
            os.environ["HUB_REPORT_ID"] = self._prev

    def _as(self, job):
        if job is None:
            os.environ.pop("HUB_REPORT_ID", None)
        else:
            os.environ["HUB_REPORT_ID"] = job
        return tp._job_profile_dir()

    def test_two_reports_do_not_share_a_profile(self):
        """The whole point — this is the collision that killed org_sales_board."""
        a = self._as("org_sales_board")
        b = self._as("captainship_activations")
        self.assertNotEqual(a, b)

    def test_the_same_report_reuses_its_profile_across_runs(self):
        """Stable per report, so it stays warm instead of paying a cold login
        every run — a fresh profile each time would be its own tax."""
        self.assertEqual(self._as("daily_focus"), self._as("daily_focus"))

    def test_an_unlabelled_run_is_unchanged(self):
        """Conservative: a hand-run script / test / REPL keeps the old shared
        profile, so nothing outside the runners changes behaviour."""
        self.assertEqual(self._as(None), tp.PROFILE_DIR)

    def test_a_blank_label_is_treated_as_unlabelled(self):
        self.assertEqual(self._as("   "), tp.PROFILE_DIR)

    def test_a_hostile_label_cannot_escape_the_profile_directory(self):
        """HUB_REPORT_ID reaches this from the environment, so a name with
        slashes or dots must not walk out of the profiles dir."""
        p = self._as("../../etc/passwd")
        self.assertEqual(p.parent, tp.PROFILE_DIR.parent)
        self.assertTrue(p.name.startswith(".browser_profile__"))
        self.assertNotIn("/", p.name)
        self.assertNotIn("..", p.name)

    def test_an_explicit_profile_dir_still_wins(self):
        """Callers that already pass their own profile (Owner Showdown,
        other_office_knocks, the crash-rebuild path) are untouched."""
        import inspect
        src = inspect.getsource(tp.tableau_session)
        self.assertIn("Path(profile_dir) if profile_dir else _job_profile_dir()",
                      src)


if __name__ == "__main__":
    unittest.main()
