"""The offboard denylist — an office turned off stays off.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.office_onboarding.test_offboarded

WHAT THIS GUARDS (Megan 2026-08-23/24). Megan asked three times to have Drew
removed. He came out of office_metrics/onboarded_offices.json,
tableau_screenshots/onboarded_trackers.json and schedule_config.json on 8/23 —
and that alone would not have held. apply.py only ever MERGES what the 'Office
Onboarding' tab holds: _merge_json adds-or-updates, _patch_schedule adds-or-
updates, neither deletes. Drew's row is still on that tab (removing it is
Megan's call — it's her data), so the next `apply --write` would have re-added
him to both registries and the schedule, and #claudecorrections-and-requests
would have started collecting drew_metrics failures again.

The denylist is what makes an offboard survive that.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.office_onboarding import apply


class _Rec:
    def __init__(self, key):
        self.key = key


def _plan(key):
    return {"rec": _Rec(key), "family": "d2d", "row": {"key": key},
            "problems": []}


class OffboardedKeysTest(unittest.TestCase):

    def test_drew_is_back(self):
        # Off the list 2026-09-28: he re-enrolled in a new channel. While he is
        # listed here the Hub refuses his metrics card and apply drops him.
        self.assertNotIn("drew", apply.OFFBOARDED_KEYS)

    def test_every_reason_is_recorded(self):
        """Whoever finds a line here in a year needs to know why it's there
        before deciding to delete it."""
        for key, why in apply.OFFBOARDED_KEYS.items():
            self.assertTrue(len(why) > 40, (key, why))
            self.assertRegex(why, r"20\d\d-\d\d-\d\d", (key, why))


class DropOffboardedTest(unittest.TestCase):

    def test_an_offboarded_office_is_dropped(self):
        with mock.patch.dict(apply.OFFBOARDED_KEYS, {"ztest": "gone 2026-01-01 for the test"}):
            kept, dropped = apply._drop_offboarded([_plan("ztest")])
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)

    def test_every_other_office_is_untouched(self):
        """The four live offices must still apply normally — this guard must not
        become a reason a healthy office stops being wired."""
        plans = [_plan(k) for k in ("haytham", "trang", "isaiah", "nii")]
        kept, dropped = apply._drop_offboarded(plans)
        self.assertEqual([p["rec"].key for p in kept],
                         ["haytham", "trang", "isaiah", "nii"])
        self.assertEqual(dropped, [])

    def test_a_mixed_batch_keeps_the_others(self):
        plans = [_plan("haytham"), _plan("ztest"), _plan("nii")]
        with mock.patch.dict(apply.OFFBOARDED_KEYS, {"ztest": "gone 2026-01-01 for the test"}):
            kept, dropped = apply._drop_offboarded(plans)
        self.assertEqual([p["rec"].key for p in kept], ["haytham", "nii"])
        self.assertEqual([p["rec"].key for p in dropped], ["ztest"])

    def test_an_empty_plan_is_fine(self):
        self.assertEqual(apply._drop_offboarded([]), ([], []))

    def test_a_plan_with_no_rec_does_not_crash(self):
        """Never let the guard itself be what breaks an apply run."""
        kept, dropped = apply._drop_offboarded([{"family": "d2d"}])
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])


class RegistriesHaveDrewBackTest(unittest.TestCase):
    """The other half, inverted 2026-09-28: Drew is back in everything that
    posts to his NEW channel -- and still out of the one thing he has no data
    for (he does not disposition in OwnerVille)."""

    NEW_CHANNEL = "C0C4YKN7QGJ"          # #precision-management-att-sales
    OLD_CHANNEL = "C0A7871FAUV"          # dead since 2026-08-15; never again

    def test_drew_is_a_metrics_office_on_the_new_channel(self):
        from automations.office_metrics import offices
        self.assertIn("drew", offices.OFFICES)
        self.assertEqual(offices.OFFICES["drew"].channel_id, self.NEW_CHANNEL)

    def test_drew_has_his_tracker_channel_and_is_not_paused(self):
        from automations.tableau_screenshots import slack_post
        self.assertEqual(slack_post.ORG_CHANNELS.get("drew"), [self.NEW_CHANNEL])
        self.assertIn("drew", slack_post.ORGS)
        self.assertNotIn("drew", slack_post.PAUSED_ORGS)

    def test_the_dead_channel_is_nowhere(self):
        from automations.office_metrics import offices
        from automations.tableau_screenshots import slack_post
        self.assertNotIn(self.OLD_CHANNEL, [o.channel_id for o in offices.OFFICES.values()])
        self.assertNotIn(self.OLD_CHANNEL, sum(slack_post.ORG_CHANNELS.values(), []))

    def test_drew_stays_out_of_weekly_knock_dispositions(self):
        # No OwnerVille dispositions = no knocks to report (Megan 2026-09-28).
        from automations.weekly_knock_dispositions import offices as wkd
        self.assertIn("drew", wkd._EXCLUDED_KEYS)

    def test_drew_has_a_schedule_entry_that_is_on(self):
        import json
        raw = json.loads(apply.SCHEDULE_CONFIG.read_text())
        reports = raw.get("reports") or raw
        self.assertTrue(reports["drew_metrics"]["on_scheduler"])
        self.assertNotIn("knocks", " ".join(reports["drew_metrics"].get("base_args", [])))


class HubCardIsRefusedTest(unittest.TestCase):
    """The door that actually let Drew back in.

    His card is a ROW IN THE SHARED LIBRARY SHEET, written by hub_coverage's
    self-registration. Code-side removal never deleted it, which is why "remove
    Drew" failed four times running."""

    def test_an_offboarded_report_id_is_offboarded(self):
        from automations.day_orchestrator import hub_coverage as hc
        with mock.patch.dict(apply.OFFBOARDED_KEYS, {"ztest": "gone 2026-01-01 for the test"}):
            self.assertTrue(hc._is_offboarded("ztest_metrics"))
            self.assertTrue(hc._is_offboarded("ztest"))
        self.assertFalse(hc._is_offboarded("drew_metrics"))   # back 2026-09-28

    def test_a_live_office_is_not(self):
        from automations.day_orchestrator import hub_coverage as hc
        for rid in ("nii_metrics", "haytham_metrics", "trang_metrics",
                    "isaiah_metrics", "daily_focus", ""):
            with self.subTest(rid=rid):
                self.assertFalse(hc._is_offboarded(rid))

    def test_a_prefix_lookalike_is_not_offboarded(self):
        """`drewsomething_metrics` is a different office, not Drew's."""
        from automations.day_orchestrator import hub_coverage as hc
        with mock.patch.dict(apply.OFFBOARDED_KEYS, {"drew": "for the test only"}):
            self.assertFalse(hc._is_offboarded("drewster_metrics"))
            self.assertFalse(hc._is_offboarded("andrew_metrics"))

    def test_ensure_library_card_refuses_and_says_why(self):
        from automations.day_orchestrator import hub_coverage as hc
        with mock.patch.dict(apply.OFFBOARDED_KEYS, {"ztest": "gone 2026-01-01 for the test"}):
            ok, msg = hc.ensure_library_card("ztest_metrics", "Z Test Daily Metrics",
                                             dry_run=True)
        self.assertFalse(ok)
        self.assertIn("offboarded", msg.lower())


if __name__ == "__main__":
    unittest.main()
