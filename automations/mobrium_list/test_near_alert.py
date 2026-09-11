"""Pins the Slack alert for people the run can't remove (Eve, 2026-09-11:
"avisar en Slack" — alert, never an automatic removal).

Slack is stubbed by patching ATTRIBUTES of the real modules, never sys.modules
(a sys.modules "mock" once posted to a real channel), and a junk token is set
as a second barrier.

Run:  python -m automations.mobrium_list.test_near_alert
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from automations.mobrium_list import plan as P
from automations.mobrium_list import run as R
from automations.mobrium_list import sheet as S
from automations.day_orchestrator import notify
from automations.shared import incident_thread


def setUpModule():
    os.environ["SLACK_USER_TOKEN"] = "xoxp-junk-for-tests"


def _entry(first, last, row=2):
    return S.Entry(row=row, first=first, last=last, email="", phone="")


def _plan(near=(), flagged=()):
    return P.Plan(removals=[], kept=[], additions=[], skipped=[], fills=[],
                  unsorted_tab=False, flagged=list(flagged), near=list(near))


class NearMissesGoToSlack(unittest.TestCase):

    def test_a_near_miss_is_posted_in_its_own_thread(self):
        plan = _plan(near=[P.NearMiss(_entry("Charley", "Perez"),
                                      "Charley Alan Perez (Wk 3) — row 2518")])
        with mock.patch.object(notify, "post_alert") as post, \
                mock.patch.object(incident_thread, "resolve_if_open") as res:
            R._alert_near(plan, real=True)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["incident"], R.NEAR_INCIDENT_KEY)
        self.assertIn("Charley Perez", "\n".join(post.call_args.args[1]))
        res.assert_not_called()

    def test_a_contradicted_board_mark_is_posted_too(self):
        plan = _plan(flagged=[P.Flagged(_entry("Ivan", "Soto"), "WE 9.13: T + sale")])
        with mock.patch.object(notify, "post_alert") as post, \
                mock.patch.object(incident_thread, "resolve_if_open"):
            R._alert_near(plan, real=True)
        self.assertIn("Ivan Soto", "\n".join(post.call_args.args[1]))

    def test_a_clean_friday_closes_the_thread(self):
        with mock.patch.object(notify, "post_alert") as post, \
                mock.patch.object(incident_thread, "resolve_if_open") as res:
            R._alert_near(_plan(), real=True)
        post.assert_not_called()
        res.assert_called_once()
        self.assertEqual(res.call_args.args[0], R.NEAR_INCIDENT_KEY)


class OnlyTheRealRunSpeaks(unittest.TestCase):

    def test_preview_or_sandbox_posts_nothing_and_closes_nothing(self):
        plan = _plan(near=[P.NearMiss(_entry("A", "B"), "x")])
        with mock.patch.object(notify, "post_alert") as post, \
                mock.patch.object(incident_thread, "resolve_if_open") as res:
            R._alert_near(plan, real=False)
            R._alert_near(_plan(), real=False)
        post.assert_not_called()
        res.assert_not_called()

    def test_main_passes_real_only_with_both_flags(self):
        import inspect
        self.assertIn("_alert_near(plan, real=args.real and args.i_mean_it)",
                      inspect.getsource(R.main))


class ItNeverCostsTheRun(unittest.TestCase):

    def test_a_slack_failure_does_not_raise(self):
        plan = _plan(near=[P.NearMiss(_entry("A", "B"), "x")])
        with mock.patch.object(notify, "post_alert",
                               side_effect=RuntimeError("slack down")):
            R._alert_near(plan, real=True)          # must not raise

    def test_the_body_says_nothing_is_removed_on_its_own(self):
        body = "\n".join(R.near_body(_plan(near=[P.NearMiss(_entry("A", "B"), "x")])))
        self.assertIn("EXACT name", body)
        self.assertIn("Nothing here gets removed on its own", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
