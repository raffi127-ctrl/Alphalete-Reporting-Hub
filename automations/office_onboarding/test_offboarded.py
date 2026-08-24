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

from automations.office_onboarding import apply


class _Rec:
    def __init__(self, key):
        self.key = key


def _plan(key):
    return {"rec": _Rec(key), "family": "d2d", "row": {"key": key},
            "problems": []}


class OffboardedKeysTest(unittest.TestCase):

    def test_drew_is_offboarded(self):
        self.assertIn("drew", apply.OFFBOARDED_KEYS)

    def test_the_reason_is_recorded(self):
        """Whoever finds this line in a year needs to know why it's there before
        deciding to delete it."""
        why = apply.OFFBOARDED_KEYS["drew"]
        self.assertTrue(len(why) > 40, why)
        self.assertIn("2026-08-23", why)


class DropOffboardedTest(unittest.TestCase):

    def test_an_offboarded_office_is_dropped(self):
        kept, dropped = apply._drop_offboarded([_plan("drew")])
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
        plans = [_plan("haytham"), _plan("drew"), _plan("nii")]
        kept, dropped = apply._drop_offboarded(plans)
        self.assertEqual([p["rec"].key for p in kept], ["haytham", "nii"])
        self.assertEqual([p["rec"].key for p in dropped], ["drew"])

    def test_an_empty_plan_is_fine(self):
        self.assertEqual(apply._drop_offboarded([]), ([], []))

    def test_a_plan_with_no_rec_does_not_crash(self):
        """Never let the guard itself be what breaks an apply run."""
        kept, dropped = apply._drop_offboarded([{"family": "d2d"}])
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])


class RegistriesAreCleanTest(unittest.TestCase):
    """The other half: Drew really is out of everything that runs today."""

    def test_drew_is_not_a_metrics_office(self):
        from automations.office_metrics import offices
        self.assertNotIn("drew", offices.OFFICES)

    def test_drew_has_no_tracker_channel(self):
        from automations.tableau_screenshots import slack_post
        self.assertNotIn("drew", slack_post.ORG_CHANNELS)
        self.assertNotIn("drew", slack_post.ORGS)

    def test_drew_is_still_paused_on_the_tracker_side_too(self):
        """Belt and braces: the registry row is gone AND the pause stands, so
        re-adding the row alone can't restart the tracker alerts."""
        from automations.tableau_screenshots import slack_post
        self.assertIn("drew", slack_post.PAUSED_ORGS)

    def test_drew_is_excluded_from_weekly_knock_dispositions(self):
        from automations.weekly_knock_dispositions import offices as wkd
        self.assertIn("drew", wkd._EXCLUDED_KEYS)

    def test_drew_has_no_schedule_entry(self):
        import json
        raw = json.loads(apply.SCHEDULE_CONFIG.read_text())
        ids = set(raw.get("reports") or {}) | set(raw)
        self.assertEqual([i for i in ids if "drew" in i.lower()], [])


class HubCardIsRefusedTest(unittest.TestCase):
    """The door that actually let Drew back in.

    His card is a ROW IN THE SHARED LIBRARY SHEET, written by hub_coverage's
    self-registration. Code-side removal never deleted it, which is why "remove
    Drew" failed four times running."""

    def test_an_offboarded_report_id_is_offboarded(self):
        from automations.day_orchestrator import hub_coverage as hc
        self.assertTrue(hc._is_offboarded("drew_metrics"))
        self.assertTrue(hc._is_offboarded("drew"))

    def test_a_live_office_is_not(self):
        from automations.day_orchestrator import hub_coverage as hc
        for rid in ("nii_metrics", "haytham_metrics", "trang_metrics",
                    "isaiah_metrics", "daily_focus", ""):
            with self.subTest(rid=rid):
                self.assertFalse(hc._is_offboarded(rid))

    def test_a_prefix_lookalike_is_not_offboarded(self):
        """`drewsomething_metrics` is a different office, not Drew's."""
        from automations.day_orchestrator import hub_coverage as hc
        self.assertFalse(hc._is_offboarded("drewster_metrics"))
        self.assertFalse(hc._is_offboarded("andrew_metrics"))

    def test_ensure_library_card_refuses_and_says_why(self):
        from automations.day_orchestrator import hub_coverage as hc
        ok, msg = hc.ensure_library_card("drew_metrics", "Drew's Daily Metrics",
                                         dry_run=True)
        self.assertFalse(ok)
        self.assertIn("offboarded", msg.lower())


if __name__ == "__main__":
    unittest.main()
