"""validate() is the last gate before a record reaches the 'Office Onboarding'
tab — a channel id that can't resolve must not get through it.

WHAT THIS GUARDS (2026-09-11). Joe typed his workspace handle,
"loganlegacygroup", into the Channel ID box on both sign-up forms. Nothing
objected: the request saved, the Slack ping went out, and the only symptom was
Lucy's membership check reporting it couldn't find the channel — by which point
he'd long left the form. The forms now refuse it at the box; this is the
backstop for anything else that builds a record.

Run:  python -m unittest automations.office_onboarding.test_channel_id_validate
"""
from __future__ import annotations

import unittest

from automations.office_onboarding import schema as S


class ChannelIdBackstop(unittest.TestCase):

    def _rec(self, cid):
        return S.OnboardingRecord(
            key="joseph", owner="Joseph Logan", knocks_office="Joseph Logan",
            business_name="Logan Legacy Group", website="", channel_id=cid,
            channel_name="joseph-logan-office", sheet_id="SHEET123",
            family="d2d", campaign="nds_d2d",
            reports=[S.EnrolledReport(key="knocks", order=1)])

    def test_the_workspace_handle_joe_typed_is_refused(self):
        problems = S.validate(self._rec("loganlegacygroup"))
        self.assertTrue(any("isn't a Slack channel ID" in p for p in problems),
                        problems)

    def test_a_channel_name_is_refused(self):
        problems = S.validate(self._rec("#joseph-logan-office"))
        self.assertTrue(any("isn't a Slack channel ID" in p for p in problems),
                        problems)

    def test_a_real_id_passes(self):
        problems = S.validate(self._rec("C0ABC12DE"))
        self.assertEqual([p for p in problems if "channel ID" in p], [])

    def test_a_bad_id_on_a_fan_out_channel_is_caught_too(self):
        rec = self._rec("C0ABC12DE")
        rec.channel_plans = [S.ChannelPlan(channel_name="#leaders",
                                           report_keys=["knocks"],
                                           channel_id="loganlegacygroup")]
        problems = S.validate(rec)
        self.assertTrue(any("channel_plans[0]" in p for p in problems), problems)

    def test_empty_still_reads_as_empty_not_malformed(self):
        """Blank keeps saying 'is empty'. Two errors for one blank box is the
        noise the 7-year-old-simple rule exists to prevent."""
        problems = S.validate(self._rec(""))
        self.assertIn("channel_id is empty.", problems)
        self.assertFalse(any("isn't a Slack channel ID" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
