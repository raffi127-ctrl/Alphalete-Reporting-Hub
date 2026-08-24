"""The per-destination channel preflight (`runner._channel_block_reason`).

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.office_metrics.test_channel_preflight

WHAT THIS GUARDS (2026-08-13, Drew / Precision Management). Drew's office reported
"0/4 metrics posted … failed: churn, rep_activations, order_log, cancels" — four
Tableau pulls, minutes each, every one of them dying at the Slack post because the
posting account could not reach the office's channel. The alert named four metrics
and never named the cause, which is a single Slack invite.

The preflight must:
  • name a MEMBERSHIP problem as such (`not_in_channel` / `channel_not_found`, or
    is_member=False on a private channel) so the alert carries the real fix;
  • treat an archived channel as unpostable;
  • stay OUT OF THE WAY otherwise — an unknown/transient Slack error returns ""
    and the run proceeds exactly as before. A preflight that guesses wrong must
    never be the reason a healthy office goes silent.
"""
from __future__ import annotations

import unittest

from automations.office_metrics import runner


class _Err(Exception):
    def __init__(self, code):
        self.response = type("R", (), {"data": {"ok": False, "error": code}})()
        super().__init__(code)


class _Client:
    """conversations.info that either raises a Slack code or returns a channel."""

    def __init__(self, raises=None, info=None):
        self._raises, self._info = raises, info

    def conversations_info(self, channel):
        if self._raises:
            raise _Err(self._raises)
        return {"channel": self._info}


class ChannelPreflightTest(unittest.TestCase):

    def test_not_in_channel_is_reported_as_membership(self):
        why = runner._channel_block_reason(_Client(raises="not_in_channel"), "C1")
        self.assertIn("not_in_channel", why)
        self.assertIn("Invite", why)

    def test_channel_not_found_says_it_is_membership_not_a_bad_id(self):
        """A PRIVATE channel returns channel_not_found to non-members, so this
        code must not send anyone off re-onboarding the office with a 'new' id."""
        why = runner._channel_block_reason(_Client(raises="channel_not_found"), "C1")
        self.assertIn("channel_not_found", why)
        self.assertIn("not a bad id", why)

    def test_private_channel_we_are_not_a_member_of(self):
        why = runner._channel_block_reason(
            _Client(info={"name": "precisionmanagement-att-sales",
                          "is_private": True, "is_member": False}), "C1")
        self.assertIn("not a member", why)
        self.assertIn("precisionmanagement-att-sales", why)

    def test_archived_channel_is_blocked(self):
        self.assertIn("is_archived", runner._channel_block_reason(
            _Client(info={"name": "old", "is_archived": True}), "C1"))

    def test_healthy_channel_is_not_blocked(self):
        self.assertEqual("", runner._channel_block_reason(
            _Client(info={"name": "nii-teiko-tagoe-office",
                          "is_private": True, "is_member": True}), "C1"))

    def test_unknown_error_never_blocks_the_run(self):
        for code in ("ratelimited", "fatal_error", "internal_error", ""):
            with self.subTest(code=code):
                self.assertEqual(
                    "", runner._channel_block_reason(_Client(raises=code or "?"), "C1"))

    def test_a_dm_or_mpim_is_not_blocked(self):
        """A review run posts into a group DM (no is_member key) — must pass."""
        self.assertEqual("", runner._channel_block_reason(
            _Client(info={"name": "mpim", "is_private": True, "is_mpim": True}), "D1"))


def _res(chan, slug, label, ok, note=""):
    """One row of runner.results: (channel_name, slug, label, ok, note)."""
    return (chan, slug, label, ok, note)


def _blocked(chan, note="channel unreachable: channel_not_found — invite her"):
    return _res(chan, "x", "x", False, note)


class CollapseBlockedFailuresTest(unittest.TestCase):
    """What the ALERT says when the only thing wrong is a Slack invite.

    Drew's office (2026-08-19 → 08-23): "*drew_metrics* dropped 5 sections this
    run", naming five healthy metrics, every day for five days. The cause was
    Lucy not being in C0A7871FAUV."""

    DREW = "Precision management-att-sales"
    BLOCKED = [(DREW, "C0A7871FAUV", "channel_not_found — invite her")]

    def _drew_results(self):
        return [_res(self.DREW, s, l, False,
                     "channel unreachable: channel_not_found — invite her")
                for s, l in (("knocks_gaps", "TeleMapper Knocks"),
                             ("churn", "Wireless Churn"),
                             ("rep_activations", "Rep Activations"),
                             ("order_log", "Order Log"),
                             ("cancels", "Canceled Orders"))]

    def test_five_held_metrics_collapse_to_one_channel_line(self):
        failed, rem = runner._collapse_blocked_failures(
            self._drew_results(), self.BLOCKED)
        self.assertEqual(len(failed), 1)
        self.assertIn(self.DREW, failed[0])
        self.assertIn("5 metric(s) held", failed[0])
        for metric in ("Wireless Churn", "Order Log", "Canceled Orders"):
            self.assertNotIn(metric, " ".join(failed))

    def test_remediation_carries_the_invite_and_the_channel_id(self):
        _failed, rem = runner._collapse_blocked_failures(
            self._drew_results(), self.BLOCKED)
        self.assertIsNotNone(rem)
        self.assertIn("Invite", rem["fix"])
        self.assertIn("C0A7871FAUV", rem["fix"])
        self.assertIn("channel_not_found", rem["reason"])

    def test_remediation_says_no_rerun_is_needed(self):
        """The metrics were never pulled — telling someone to re-run sends them
        round a loop that cannot succeed until the invite happens."""
        _f, rem = runner._collapse_blocked_failures(
            self._drew_results(), self.BLOCKED)
        self.assertIn("Nothing else needs re-running", rem["fix"])

    def test_real_metric_failures_are_still_named(self):
        """A blocked channel must never become a place real breakage hides."""
        results = self._drew_results() + [
            _res("nii-office", "churn", "Wireless Churn", False, "tableau timeout"),
            _res("nii-office", "order_log", "Order Log", True, ""),
        ]
        failed, _rem = runner._collapse_blocked_failures(results, self.BLOCKED)
        self.assertIn("Wireless Churn", failed)
        self.assertTrue(any(self.DREW in f for f in failed))

    def test_two_blocked_channels_get_one_line_each(self):
        blocked = [("office-a", "C1", "channel_not_found — invite her"),
                   ("office-b", "C2", "not_in_channel — invite her")]
        results = [_blocked("office-a"), _blocked("office-a"),
                   _blocked("office-b")]
        failed, rem = runner._collapse_blocked_failures(results, blocked)
        self.assertEqual(len(failed), 2)
        self.assertIn("C1", rem["fix"])
        self.assertIn("C2", rem["fix"])

    def test_nothing_blocked_behaves_exactly_as_before(self):
        results = [_res("c", "churn", "Wireless Churn", False, "tableau timeout"),
                   _res("c", "order_log", "Order Log", True, "")]
        failed, rem = runner._collapse_blocked_failures(results, [])
        self.assertEqual(failed, ["Wireless Churn"])
        self.assertIsNone(rem)

    def test_a_clean_run_reports_nothing(self):
        failed, rem = runner._collapse_blocked_failures(
            [_res("c", "churn", "Wireless Churn", True, "")], [])
        self.assertEqual(failed, [])
        self.assertIsNone(rem)

    def test_a_normal_failure_in_a_blocked_channel_is_not_swallowed(self):
        """Same channel, but this metric died on its own (no unreachable note) —
        it has to keep its name, or a real break inside a blocked office would
        vanish the moment the invite lands."""
        results = [_blocked(self.DREW),
                   _res(self.DREW, "churn", "Wireless Churn", False,
                        "exit 1: tableau view missing")]
        failed, _rem = runner._collapse_blocked_failures(results, self.BLOCKED)
        self.assertIn("Wireless Churn", failed)


if __name__ == "__main__":
    unittest.main()
