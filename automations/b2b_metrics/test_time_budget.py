"""A run that outgrows its cap must degrade to a NAMED partial, never a SIGKILL.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.b2b_metrics.test_time_budget

WHAT THIS GUARDS (2026-09-04). The 4am `--all --post` was killed at its 30-minute
cap. Nothing hung — the report had simply outgrown a cap written for the two
offices that existed in July. Measured that morning: Carlos's 9 sections ran
05:04->05:11, Atef's 10 ran 05:11->05:31, and the SIGKILL landed at 05:34 with
Jamis and Sabrina never started.

The lateness was survivable; the KILL was not. The process dies between the
capture loop and `_write_manifest`, so the run records nothing — the orchestrator
cannot name which sections are still missing, and the retry re-runs all 41
against the same cap instead of backfilling the two offices that were left.

So the runner now reads the budget the orchestrator already exports
(HUB_REPORT_TIMEOUT_S) and stops starting offices it cannot finish. The contract:

  • the FIRST office always runs — a too-small budget still produces a thread;
  • the yardstick is the SLOWEST office so far, not an average (the per-office
    cost varies 3x, and an average keeps starting offices that then get killed);
  • an unstarted office is recorded like a crashed one — every expected section
    in failed[] — so the manifest names them and the retry comes back for
    exactly those;
  • with NO budget in the environment (a hand run, a LaunchAgent) there is no
    deadline at all and the behaviour is what it always was.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.b2b_metrics import offices as _off
from automations.b2b_metrics import runner


class _Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _run_main(*, budget_s, office_cost_s, argv=("--all", "--post")):
    """Drive runner.main() with a fake clock and a stubbed per-office run().

    Returns (exit_code, manifest_kwargs, office_keys_actually_run).
    """
    clock = _Clock()
    ran: list = []
    written: list = []

    def fake_run(o, **kw):
        ran.append(o.key)
        clock.now += office_cost_s.get(o.key, 60.0)
        ids = runner.expected_ids(o)
        return {"thread_ts": "1.1", "posted": ids, "present": ids,
                "missed": [], "deferred": [], "no_data": []}

    env = {} if budget_s is None else {"HUB_REPORT_TIMEOUT_S": str(budget_s)}
    fake_tb = mock.Mock()
    fake_tb.sync = mock.Mock()
    with mock.patch.object(runner.time, "monotonic", clock), \
         mock.patch.object(runner, "_PROCESS_START", clock.now), \
         mock.patch.dict("os.environ", env, clear=False), \
         mock.patch.dict("sys.modules", {"automations.thread_builder.sync": fake_tb}), \
         mock.patch.object(runner, "run", fake_run), \
         mock.patch.object(runner, "_write_manifest",
                           lambda per_office, scoped=False: written.append(
                               {"per_office": per_office, "scoped": scoped})), \
         mock.patch.object(runner, "_publish_hub", mock.Mock()), \
         mock.patch.object(runner, "_publish_running", mock.Mock()), \
         mock.patch.object(runner, "_record_office_status", mock.Mock()):
        if budget_s is None:
            # An inherited budget from a real orchestrator run would make the
            # "uncapped" case a lie.
            import os
            os.environ.pop("HUB_REPORT_TIMEOUT_S", None)
        rc = runner.main(list(argv))
    return rc, (written[-1] if written else None), ran


ALL_OFFICES = list(_off.ORDER)
# 15 minutes each — between Carlos's real 7 and Atef's real 20 on 2026-09-04.
# Four of them (60 min) fit the 75-minute cap and do not fit the old 30.
SLOW = {k: 15 * 60.0 for k in ALL_OFFICES}


class TheBudgetIsReadFromTheEnvironment(unittest.TestCase):

    def test_no_budget_means_no_deadline(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("HUB_REPORT_TIMEOUT_S", None)
            self.assertIsNone(runner._budget_deadline())

    def test_junk_never_shortens_a_report(self):
        for bad in ("", "   ", "abc", "0", "-60"):
            with mock.patch.dict("os.environ", {"HUB_REPORT_TIMEOUT_S": bad}):
                self.assertIsNone(runner._budget_deadline(), bad)

    def test_the_deadline_leaves_room_to_write_the_manifest(self):
        with mock.patch.object(runner, "_PROCESS_START", 0.0), \
             mock.patch.dict("os.environ", {"HUB_REPORT_TIMEOUT_S": "1800"}):
            self.assertEqual(runner._budget_deadline(),
                             1800 - runner._WRAPUP_SEC)


class AGenerousBudgetChangesNothing(unittest.TestCase):

    def test_every_office_runs(self):
        rc, manifest, ran = _run_main(budget_s=75 * 60, office_cost_s=SLOW)
        self.assertEqual(ran, ALL_OFFICES)
        self.assertEqual(rc, 0)
        self.assertEqual(manifest["per_office"][0]["missed"], [])

    def test_an_absent_budget_runs_them_all_too(self):
        rc, _m, ran = _run_main(budget_s=None, office_cost_s=SLOW)
        self.assertEqual(ran, ALL_OFFICES)
        self.assertEqual(rc, 0)


class ATightBudgetStopsInsteadOfBeingKilled(unittest.TestCase):
    """The 2026-09-04 shape: a 30-minute cap and 20-minute offices."""

    def setUp(self):
        self.rc, self.manifest, self.ran = _run_main(
            budget_s=30 * 60, office_cost_s=SLOW)

    def test_it_stops_before_the_cap(self):
        # 30m budget, 20m offices: one fits, the second cannot.
        self.assertEqual(self.ran, ALL_OFFICES[:1])

    def test_the_manifest_is_still_written(self):
        """THE POINT. A SIGKILL wrote nothing; this must write."""
        self.assertIsNotNone(self.manifest)

    def test_the_unstarted_offices_are_named_as_missing(self):
        by_key = {po["key"]: po for po in self.manifest["per_office"]}
        self.assertEqual(sorted(by_key), sorted(ALL_OFFICES))
        for key in ALL_OFFICES[1:]:
            o = _off.get(key)
            self.assertEqual(by_key[key]["missed"], runner.expected_ids(o), key)
            self.assertTrue(by_key[key]["failed"], key)
            self.assertEqual(by_key[key]["present"], [], key)

    def test_the_office_that_ran_keeps_its_clean_verdict(self):
        by_key = {po["key"]: po for po in self.manifest["per_office"]}
        first = by_key[ALL_OFFICES[0]]
        self.assertEqual(first["missed"], [])
        self.assertFalse(first["failed"])

    def test_it_exits_non_zero_so_the_retry_runs(self):
        self.assertEqual(self.rc, 2)


class TheFirstOfficeAlwaysRuns(unittest.TestCase):
    """A budget too small for ANY office still has to produce a thread —
    stopping at zero offices would be a worse morning than being killed."""

    def test_one_office_runs_even_on_an_absurd_budget(self):
        rc, manifest, ran = _run_main(budget_s=120, office_cost_s=SLOW)
        self.assertEqual(ran, ALL_OFFICES[:1])
        self.assertIsNotNone(manifest)
        self.assertEqual(rc, 2)


class TheYardstickIsTheSlowestOfficeNotTheAverage(unittest.TestCase):
    """Carlos 7 min then Atef 20 min: after those two, ~25 min of a 60-minute
    budget is left. An AVERAGE (13.5 min) would start a third office that then
    gets killed 5 minutes short; the slowest-so-far (20 min) starts it only
    because it genuinely fits."""

    def test_a_cheap_first_office_does_not_licence_a_doomed_third(self):
        costs = dict.fromkeys(ALL_OFFICES, 20 * 60.0)
        costs[ALL_OFFICES[0]] = 7 * 60.0
        # 7 + 20 = 27 min spent; 60 - 27 = 33 min left, so a 20-minute office
        # fits and the fourth (13 min left) does not.
        rc, manifest, ran = _run_main(budget_s=60 * 60, office_cost_s=costs)
        self.assertEqual(ran, ALL_OFFICES[:3])
        by_key = {po["key"]: po for po in manifest["per_office"]}
        self.assertTrue(by_key[ALL_OFFICES[3]]["failed"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
