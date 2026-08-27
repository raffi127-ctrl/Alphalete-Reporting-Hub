"""Triage is a SORTING decision, so the tests are about which bucket, not about
Slack. Every case here is a real shape seen in #claudecorrections-and-requests.

The bias under test: NEEDS_YOU is the expensive verdict (it sends a person to
open a thread), so it must never win while the orchestrator still has retry
budget and the failure looks transient.
"""
import datetime as dt
import unittest
from unittest import mock

from automations.shared import incident_triage as tri

DAY = dt.date(2026, 8, 26)


def _classify(key="failure-x", tail="", opened=DAY.isoformat(), repeats=0, hour=6):
    with mock.patch.object(tri, "_log_tail", return_value=tail.lower()):
        return tri.classify(key, day=DAY, opened=opened, repeats=repeats,
                            now_hour=hour)


class Buckets(unittest.TestCase):

    def test_deleted_tableau_view_is_yours_even_at_4am(self):
        """The signature outranks the clock: no number of retries brings a
        deleted view back, so it must not sit in :pending: until noon."""
        v = _classify(tail="Traceback\n  view not found: OPT AUTOMATIONPULL")
        self.assertEqual(v.bucket, tri.NEEDS_YOU)
        self.assertIn("Tableau view", v.reason)

    def test_expired_login_early_is_lucys(self):
        v = _classify(tail="appstream session expired — no live token")
        self.assertEqual(v.bucket, tri.LUCY)

    def test_same_expired_login_after_noon_is_yours(self):
        """Past the backstop the loop has stopped retrying, so 'pending' would
        be a lie — nothing is going to pick it up again."""
        v = _classify(tail="appstream session expired", hour=13)
        self.assertEqual(v.bucket, tri.NEEDS_YOU)
        self.assertIn("noon", v.reason)

    def test_source_not_posted_is_waiting(self):
        v = _classify(tail="waiting on source: no board posted today")
        self.assertEqual(v.bucket, tri.WAITING)

    def test_open_since_yesterday_is_yours(self):
        """A full morning of automatic retries already lost. Whatever the log
        says, day two is a person's."""
        v = _classify(tail="timed out", opened="2026-08-25")
        self.assertEqual(v.bucket, tri.NEEDS_YOU)
        self.assertIn("yesterday", v.reason)

    def test_retry_budget_spent_is_yours(self):
        v = _classify(tail="connection reset", repeats=3)
        self.assertEqual(v.bucket, tri.NEEDS_YOU)
        self.assertIn("3 times", v.reason)

    def test_two_repeats_is_still_lucys(self):
        """MAX_RUN_RETRIES is 3 — at two it has budget left."""
        v = _classify(tail="connection reset", repeats=2)
        self.assertEqual(v.bucket, tri.LUCY)

    def test_unreadable_log_early_stays_with_lucy(self):
        v = _classify(tail="")
        self.assertEqual(v.bucket, tri.LUCY)

    def test_unreadable_log_after_noon_is_yours(self):
        v = _classify(tail="", hour=12)
        self.assertEqual(v.bucket, tri.NEEDS_YOU)


class TheLine(unittest.TestCase):
    """Megan 2026-08-26: simple, clear, no fluff. Enforced, not just intended."""

    def test_no_emoji_in_any_line(self):
        for bucket in (tri.NEEDS_YOU, tri.LUCY, tri.WAITING):
            line = tri.line_for(tri.Verdict("k", bucket, "Something broke."))
            self.assertNotIn(":", line.replace("*", ""),
                             "emoji/colons belong in the reaction layer")

    def test_every_line_says_what_to_do(self):
        for bucket in (tri.NEEDS_YOU, tri.LUCY, tri.WAITING):
            line = tri.line_for(tri.Verdict("k", bucket, "Something broke."))
            self.assertTrue(
                "Needs one of you" in line or "Nothing for you to do" in line,
                "a triage line that doesn't say whether to act is fluff: " + line)

    def test_lines_stay_short(self):
        for bucket in (tri.NEEDS_YOU, tri.LUCY, tri.WAITING):
            line = tri.line_for(tri.Verdict("k", bucket, "Something broke."))
            self.assertLess(len(line), 220, "this is the wall of text we removed")


class ReportId(unittest.TestCase):

    def test_strips_every_family_prefix(self):
        self.assertEqual(tri.report_id("failure-b2b_metrics"), "b2b_metrics")
        self.assertEqual(tri.report_id("drop-daily_metrics"), "daily_metrics")
        self.assertEqual(tri.report_id("b2b_metrics"), "b2b_metrics")


class OneReactionOnly(unittest.TestCase):
    """A post wearing two answers is worse than an unmarked one."""

    def setUp(self):
        self.calls = []

        def fake_react(client, channel, ts, name, remove=False):
            self.calls.append(("remove" if remove else "add", name))
            return True

        self.p = mock.patch.object(tri.inc, "_react", fake_react)
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_switching_bucket_removes_the_old_circle(self):
        tri._apply(None, "C1", "1.0", tri.NEEDS_YOU,
                   [tri.inc.WORKING_REACTION], dry_run=False)
        self.assertIn(("remove", tri.inc.WORKING_REACTION), self.calls)
        self.assertIn(("add", tri.NEEDS_YOU_REACTION), self.calls)

    def test_already_correct_costs_no_api_calls(self):
        changed = tri._apply(None, "C1", "1.0", tri.LUCY,
                             [tri.inc.WORKING_REACTION], dry_run=False)
        self.assertFalse(changed)
        self.assertEqual(self.calls, [])

    def test_never_touches_the_white_check(self):
        tri._apply(None, "C1", "1.0", tri.LUCY,
                   ["white_check_mark", tri.NEEDS_YOU_REACTION], dry_run=False)
        self.assertNotIn(("remove", "white_check_mark"), self.calls)


class WhatGetsGraded(unittest.TestCase):
    """The ✅ outranks the marker text — the bug the first dry run caught, where
    6 already-fixed posts were about to get a red circle."""

    def _scan(self, messages, prior=None):
        with mock.patch.object(tri.inc, "_history", return_value=messages), \
             mock.patch.object(tri.inc, "_load_index", return_value={}):
            return tri._open_incidents(None, "C1", DAY, prior)

    @staticmethod
    def _post(key, opened, reactions=(), extra=""):
        return {"ts": "1.0",
                "text": "*Something* — broke{}\n\n_incident · {} · open {}_"
                        .format(extra, key, opened),
                "reactions": [{"name": r} for r in reactions]}

    def test_check_mark_wins_over_an_open_marker(self):
        gradeable, fixed, _, _ = self._scan([
            self._post("failure-a", DAY.isoformat(), ["white_check_mark"])])
        self.assertEqual(gradeable, [])
        self.assertEqual(fixed, ["failure-a"])

    def test_resolved_in_the_text_also_counts_as_fixed(self):
        gradeable, fixed, _, _ = self._scan([
            self._post("failure-a", DAY.isoformat(), extra=" · RESOLVED 8/26")])
        self.assertEqual(gradeable, [])
        self.assertEqual(fixed, ["failure-a"])

    def test_a_week_old_marker_is_stale_not_urgent(self):
        gradeable, _, stale, _ = self._scan([
            self._post("failure-a", "2026-08-01")])
        self.assertEqual(gradeable, [])
        self.assertEqual(stale, ["failure-a"])

    def test_a_genuinely_open_post_is_graded(self):
        gradeable, fixed, stale, _ = self._scan([
            self._post("failure-a", DAY.isoformat())])
        self.assertEqual([g["key"] for g in gradeable], ["failure-a"])
        self.assertEqual((fixed, stale), ([], []))

    def test_resolved_marker_state_is_ignored_entirely(self):
        gradeable, fixed, stale, gated = self._scan([{
            "ts": "1.0",
            "text": "*x* — y\n\n_incident · failure-a · resolved 2026-08-26_",
            "reactions": []}])
        self.assertEqual((gradeable, fixed, stale, gated), ([], [], [], []))

    def test_a_pending_someone_else_set_is_left_alone(self):
        """:pending: means a PERSON is on it — the one signal that stops two
        people starting the same ticket. Red is the vaguer claim; it loses."""
        gradeable, _, _, gated = self._scan([
            self._post("failure-a", DAY.isoformat(), ["pending"])])
        self.assertEqual(gradeable, [])
        self.assertEqual(gated, ["failure-a"])

    def test_a_pending_triage_itself_assigned_is_still_ours(self):
        gradeable, _, _, gated = self._scan(
            [self._post("failure-a", DAY.isoformat(), ["pending"])],
            prior={"failure-a": {"bucket": tri.LUCY}})
        self.assertEqual([g["key"] for g in gradeable], ["failure-a"])
        self.assertEqual(gated, [])

    def test_approval_gate_purple_is_left_alone(self):
        """The gate's purple already points at a person and says which action
        they owe. Red would say 'needs a code fix' about a working report."""
        gradeable, _, _, gated = self._scan([
            self._post("standalone-drafts", DAY.isoformat(),
                       ["large_purple_circle"])])
        self.assertEqual(gradeable, [])
        self.assertEqual(gated, ["standalone-drafts"])

    def test_a_purple_triage_itself_assigned_is_still_ours(self):
        gradeable, _, _, gated = self._scan(
            [self._post("failure-a", DAY.isoformat(), ["large_purple_circle"])],
            prior={"failure-a": {"bucket": tri.WAITING}})
        self.assertEqual([g["key"] for g in gradeable], ["failure-a"])
        self.assertEqual(gated, [])


class NoticesNotWork(unittest.TestCase):
    """A `drop-tableau-stale-` key is an upstream feed running behind, not a
    broken report. Its own alert says there is nothing on our side to change, so
    a red circle on it sends two people to open a thread that tells them to go
    away — the precise way a red circle stops being believed."""

    KEY = "drop-tableau-stale-atttracker2-1-d2d-fiberleadperformance"

    def test_never_red_however_old(self):
        v = _classify(key=self.KEY, tail="", opened="2026-08-01", hour=15)
        self.assertEqual(v.bucket, tri.WAITING)

    def test_beats_the_age_rule(self):
        """The age rule is checked first for everything else — this must jump it,
        because these stay open for days by their nature."""
        v = _classify(key=self.KEY, opened="2026-08-25")
        self.assertNotEqual(v.bucket, tri.NEEDS_YOU)

    def test_line_does_not_promise_a_rerun(self):
        v = _classify(key=self.KEY, opened="2026-08-25")
        line = tri.line_for(v)
        self.assertIn("Nothing to do", line)
        self.assertNotIn("re-runs it", line)
        self.assertNotIn("Needs one of you", line)

    def test_an_ordinary_drop_key_is_unaffected(self):
        v = _classify(key="drop-daily_metrics", opened="2026-08-25")
        self.assertEqual(v.bucket, tri.NEEDS_YOU)


class FinishesStrandedMarkers(unittest.TestCase):
    """A post with the ✅ and an `open` marker is closed to a person and open to
    every machine. Triage has always DETECTED that state — it has to, or it
    would put a red circle on a fixed post — and only ever counted it. It
    finishes them now (Megan 2026-08-26)."""

    def _run(self, fixed, close_result=None, close_raises=None):
        close = mock.Mock(side_effect=close_raises) if close_raises else \
            mock.Mock(return_value=close_result or {"closed": [], "not_ours": []})
        with mock.patch.object(tri, "_open_incidents",
                               return_value=([], fixed, [], [])), \
             mock.patch.object(tri, "_load_state", return_value={}), \
             mock.patch.object(tri, "_save_state"), \
             mock.patch.object(tri.inc, "_client", return_value=None), \
             mock.patch.object(tri.inc, "close_stranded", close):
            out = tri.run(day=DAY, channel="C1", dry_run=True)
        return out, close

    def test_a_stranded_marker_gets_finished(self):
        _, close = self._run(["failure-a"],
                             {"closed": ["failure-a"], "not_ours": []})
        self.assertEqual(close.call_count, 1)
        self.assertTrue(close.call_args.kwargs.get("dry_run"))

    def test_no_stranded_markers_costs_no_extra_scan(self):
        """The common case is a clean channel — don't pay for a second walk."""
        _, close = self._run([])
        self.assertEqual(close.call_count, 0)

    def test_bookkeeping_never_breaks_the_triage_pass(self):
        """The reactions are the point; finishing a marker is a bonus."""
        out, close = self._run(["failure-a"],
                               close_raises=RuntimeError("slack down"))
        self.assertEqual(close.call_count, 1)
        self.assertEqual(out, {tri.NEEDS_YOU: [], tri.LUCY: [], tri.WAITING: []})


if __name__ == "__main__":
    unittest.main()
