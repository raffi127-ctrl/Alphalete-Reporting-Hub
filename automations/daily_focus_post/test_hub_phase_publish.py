"""The 7 PM post has to TELL THE HUB, not just write a manifest.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.daily_focus_post.test_hub_phase_publish

WHY (Megan 2026-09-04). Daily Recruiting Focus is a two-phase card — the fill
(`daily-focus`) and this 7 PM office post (`daily-focus-post`) — and its pill
only goes green when BOTH phases record a run that day. From 2026-08-31, the
first day the post went live, Raf's post landed every weekday at 7 PM and the
card still read amber "1/2 done" every single day. `daily-focus-post` had never
written one row to the Hub Activity sheet, ever.

The run wrote a `run_manifest` and stopped there. That manifest is a local JSON
file on whichever Lucy ran the post; the Hub reads the shared "Hub Activity"
sheet and nothing else, so from Megan's laptop the phase looked like it had
never happened. Every other two-phase card's second phase (org_sales_board_email,
country_sales_board_email, the review gates) publishes a row — this one was the
only one that didn't.

These tests drive main() with the roster, the spreadsheet and both reporting
paths stubbed. Nothing touches Google, Slack or the network.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.daily_focus_post import run as R


class _Office:
    def __init__(self, key):
        self.key = key
        self.label = key.title()
        self.owner = f"{key} owner"
        self.tab = key
        self.timezone = "America/Chicago"
        self.channel_id = "C000"


def _drive(argv, offices, fail_keys=(), skip_keys=()):
    """Run main() with everything outward stubbed. Returns the log_completed mock."""
    hub = mock.Mock(return_value=True)

    def _post(office, spreadsheet, **kw):
        if office.key in fail_keys:
            raise RuntimeError("boom")
        if office.key in skip_keys:
            return {"office": office.key, "skipped": "already_posted"}
        return {"office": office.key}

    with mock.patch.object(R.roster, "validate", return_value=[]), \
            mock.patch.object(R.roster, "ROSTER", offices), \
            mock.patch.object(R.fill, "open_by_key", return_value=object()), \
            mock.patch.object(R, "post_office", side_effect=_post), \
            mock.patch.object(R.run_manifest, "write_manifest"), \
            mock.patch("automations.shared.hub_activity.log_completed", hub):
        R.main(argv)
    return hub


class PublishesItsPhase(unittest.TestCase):

    def test_a_live_post_writes_the_phase_row(self):
        hub = _drive(["--live"], [_Office("raf")])
        hub.assert_called_once()
        args, kwargs = hub.call_args
        self.assertEqual(args[0], R.REPORT_ID)
        self.assertEqual(kwargs["status"], "success")

    def test_the_phase_id_matches_the_card(self):
        """A typo here is invisible: the post still goes out, the pill just
        never moves. The card is the contract."""
        from automations.hub_cards import AUTOMATED_REPORTS
        card = next(c for c in AUTOMATED_REPORTS if c["id"] == "daily-focus")
        self.assertIn(R.REPORT_ID, card["phases"])

    def test_it_never_registers_a_card_of_its_own(self):
        """It is a PHASE of Daily Recruiting Focus. Auto-registering would put a
        second, permanently-white tile on the Hub next to the real card."""
        hub = _drive(["--live"], [_Office("raf")])
        self.assertIs(hub.call_args.kwargs["register_card"], False)

    def test_a_dry_run_reports_nothing(self):
        """A preview must not paint a green pill for a post that didn't happen."""
        hub = _drive(["--dry-run"], [_Office("raf")])
        hub.assert_not_called()

    def test_nothing_due_reports_nothing(self):
        """Zero offices due (a weekend, or before 7 PM) is not a clean day —
        marking it success at breakfast would hide a 7 PM that never came."""
        hub = _drive(["--live"], [])
        hub.assert_not_called()

    def test_every_office_failing_is_failed_not_success(self):
        hub = _drive(["--live"], [_Office("raf")], fail_keys={"raf"})
        self.assertEqual(hub.call_args.kwargs["status"], "failed")

    def test_some_offices_failing_is_partial(self):
        hub = _drive(["--live"], [_Office("raf"), _Office("carlos")],
                     fail_keys={"carlos"})
        self.assertEqual(hub.call_args.kwargs["status"], "partial")

    def test_an_already_posted_tick_reports_nothing(self):
        """The LaunchAgent ticks every 10 minutes and the office stays due for
        the whole 3-hour grace window, so ~17 ticks reach main() for ONE post.
        Only the tick that actually posts is work: on 2026-09-04 the other 16
        each wrote their own duplicate Hub row."""
        hub = _drive(["--live"], [_Office("raf")], skip_keys={"raf"})
        hub.assert_not_called()

    def test_a_new_office_still_reports_when_another_already_posted(self):
        """Offices post at their OWN local 7 PM, so a later tick legitimately
        carries one real post beside one already-posted skip."""
        hub = _drive(["--live"], [_Office("raf"), _Office("carlos")],
                     skip_keys={"raf"})
        hub.assert_called_once()
        self.assertEqual(hub.call_args.kwargs["status"], "success")

    def test_a_skipped_office_does_not_mask_a_failure(self):
        """raf already posted, carlos blew up: nobody did new work that tick,
        so the row must read failed — not partial off the stale skip."""
        hub = _drive(["--live"], [_Office("raf"), _Office("carlos")],
                     skip_keys={"raf"}, fail_keys={"carlos"})
        self.assertEqual(hub.call_args.kwargs["status"], "failed")


if __name__ == "__main__":
    unittest.main()
