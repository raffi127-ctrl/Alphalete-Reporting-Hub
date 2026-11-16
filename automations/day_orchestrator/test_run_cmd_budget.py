"""Every timed verb tells its child the deadline, not just `rerun`.

2026-11-16: five `probe_knocks` runs were queued back to back. They contend for
the same browser profile, so one lost the race, logged

    [ownerville_session] another run holds .browser_profile.launchlock
      (pid ..., pid ...) — waiting up to 30m for it to finish

and was killed at its own 900s timeout while still waiting. It had read
nothing, so it looked like "that day's Disposition grid is broken" and cost six
more ownerville probes to disprove.

tableau_patchright._profile_wait_budget() already exists to prevent exactly
that: it caps the wait at a share of HUB_REPORT_TIMEOUT_S and only falls back
to the flat 30-minute ceiling when that variable is unset. `_action_rerun`
exported it; no other verb did. _run_cmd is the one chokepoint every action
passes through, so it is set there.

Run:  python -m unittest automations.day_orchestrator.test_run_cmd_budget
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from automations.day_orchestrator import mini_control as mc
from automations.shared import tableau_patchright as TP


class _Killed(Exception):
    """Popen is stubbed out — the env is captured before anything launches.

    It carries a MESSAGE on purpose: _run_cmd's launch-error handler does
    `str(e).splitlines()[0]`, which IndexErrors on an exception whose str() is
    empty. Not this test's business to fix, but worth knowing it is there.
    """


class EveryChildLearnsItsDeadline(unittest.TestCase):

    def _env_for(self, **kw):
        seen = {}

        def _popen(cmd, **k):
            seen.update(k.get("env") or {})
            raise _Killed("stubbed, never launched")

        with mock.patch.object(mc.subprocess, "Popen", _popen):
            mc._run_cmd(["true"], **kw)
        return seen

    def test_the_timeout_reaches_the_child(self):
        env = self._env_for(timeout_s=900)
        self.assertEqual(env.get("HUB_REPORT_TIMEOUT_S"), "900")

    def test_it_is_set_even_with_no_other_env(self):
        # probe_knocks for the master office passes env=None.
        env = self._env_for(timeout_s=600)
        self.assertEqual(env.get("HUB_REPORT_TIMEOUT_S"), "600")

    def test_the_caller_can_still_override(self):
        env = self._env_for(timeout_s=900,
                            env={"HUB_REPORT_TIMEOUT_S": "120"})
        self.assertEqual(env.get("HUB_REPORT_TIMEOUT_S"), "120")

    def test_other_env_vars_survive(self):
        env = self._env_for(timeout_s=900, env={"KNOCKS_OFFICE": "Carlos"})
        self.assertEqual(env.get("KNOCKS_OFFICE"), "Carlos")
        self.assertEqual(env.get("HUB_REPORT_TIMEOUT_S"), "900")

    def test_the_real_environment_is_still_inherited(self):
        with mock.patch.dict(os.environ, {"PATH_CANARY": "yes"}):
            env = self._env_for(timeout_s=900)
        self.assertEqual(env.get("PATH_CANARY"), "yes")


class TheBudgetActuallyShortensTheWait(unittest.TestCase):
    """The point of exporting it: the profile wait must come in UNDER the
    verb's own timeout, or the run dies mid-wait having done nothing."""

    def test_a_15_minute_verb_waits_less_than_15_minutes(self):
        with mock.patch.dict(os.environ, {"HUB_REPORT_TIMEOUT_S": "900"}):
            self.assertLess(TP._profile_wait_budget(), 900)

    def test_without_it_the_wait_outlives_the_verb(self):
        # The old behaviour, kept as the reason this test file exists.
        env = dict(os.environ)
        env.pop("HUB_REPORT_TIMEOUT_S", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertGreater(TP._profile_wait_budget(), 900)

    def test_the_floor_is_respected_for_a_short_verb(self):
        with mock.patch.dict(os.environ, {"HUB_REPORT_TIMEOUT_S": "30"}):
            self.assertGreaterEqual(TP._profile_wait_budget(),
                                    TP._PROFILE_WAIT_FLOOR_S)


if __name__ == "__main__":
    unittest.main()
