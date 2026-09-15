"""An owner with no Slack must be able to SAY so on the request form.

WHAT THIS GUARDS (2026-09-15). validate_request() demanded a Slack channel from
every owner, so "I don't use Slack" was not a sayable answer on the owner-facing
form. Christian Esposito (Resound, Inc.) hit that on 2026-09-07 and did the only
thing the form left him: he filled in a channel he could not read. His sign-up
then sat in the queue describing a delivery that was never going to work, and
Raf had to ask for email by hand a week later.

The rule these tests pin: a request carries EITHER a channel OR addresses, each
validated on its own terms, and neither answer is allowed to demand the other's
fields [[project_email_only_offices]].

Run:  python -m unittest automations.office_onboarding.test_email_request
"""
from __future__ import annotations

import unittest

from automations.office_onboarding import schema as S


def _rec(**kw):
    base = dict(
        key="resound", owner="Christian Esposito",
        knocks_office="Christian Esposito", business_name="Resound, Inc.",
        website="https://resound-fl.com/", owner_email="resoundinc@gmail.com",
        channel_id="", channel_name="", sheet_id="",
        family="d2d", campaign="fiber_d2d",
        reports=[S.EnrolledReport(key="knocks", order=1)])
    base.update(kw)
    return S.OnboardingRecord(**base)


class EmailRequest(unittest.TestCase):

    def test_email_request_needs_no_channel(self):
        """The whole point: addresses instead of a channel, and it validates."""
        self.assertEqual(
            S.validate_request(_rec(email_to=["resoundinc@gmail.com"])), [])

    def test_email_request_refuses_a_non_address(self):
        problems = S.validate_request(_rec(email_to=["resoundinc"]))
        self.assertTrue(any("email address" in p for p in problems), problems)

    def test_email_request_still_needs_a_metric(self):
        """No channel to hang the picks off, so the enrolment is what counts —
        an empty one must not sail through just because an address is present."""
        problems = S.validate_request(
            _rec(email_to=["resoundinc@gmail.com"], reports=[]))
        self.assertTrue(any("at least one metric" in p for p in problems),
                        problems)

    def test_slack_request_is_unchanged(self):
        """The existing answer keeps its existing gate — an owner who picks
        Slack and names no channel is still told so."""
        problems = S.validate_request(_rec())
        self.assertTrue(any("Slack channel" in p for p in problems), problems)

    def test_slack_request_with_a_channel_passes(self):
        ok = _rec(channel_plans=[S.ChannelPlan(
            channel_name="#resound-sales", channel_id="C0BQD2G324D",
            report_keys=["knocks"])])
        self.assertEqual(S.validate_request(ok), [])

    def test_never_both(self):
        """validate() (the finalize gate) refuses an office holding a channel
        AND addresses — two destinations, no single answer to 'did today go
        out?'. Pinned here so the request path can never talk it into one."""
        both = _rec(channel_id="C0BQD2G324D", channel_name="#resound-sales",
                    email_to=["resoundinc@gmail.com"], sheet_id="sheet123")
        problems = S.validate(both, existing_keys=set())
        self.assertTrue(any("BOTH" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
