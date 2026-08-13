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


if __name__ == "__main__":
    unittest.main()
