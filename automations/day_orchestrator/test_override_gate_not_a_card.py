"""The Override Bulletin's review-gate HANDLE must not get its own Hub card.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_override_gate_not_a_card

WHAT THIS GUARDS (Megan 2026-09-04, "this should be green since it went out").
`override_bulletin_gate` self-registered a library card on 8/30 whose stored
schedule was {"frequency": "weekly", "weekdays": [4]}, so every Friday it also
put a line on Lucy 1's due-today list. That line could never tick: override_gate
publishes under the card id `override_bulletin`, so the Friday send greened the
🏆 card while the stub sat unchecked right beside it, reading as "the bulletin
didn't go out" on the day it went out to 92 people.

It was a DUPE, not a report — post / send / preview are already buttons on the
🏆 card — so the stub went and the schedule_config entry stayed (`lucy rerun
override_bulletin_gate` still works; it just isn't CARDED).

Both spellings are listed for the reason owner_showdown documents: sync() keys
on the report_id, sync_launchd_system() derives the kebab id from the plist
label, and a row deleted while only one door is shut comes straight back.
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator import hub_coverage as hc


class TheGateHandleIsNotAReport(unittest.TestCase):

    def test_both_spellings_are_declared_internal(self):
        # Underscore = the scheduler door; kebab = the plist door.
        self.assertTrue(hc.is_internal("override_bulletin_gate"))
        self.assertTrue(hc.is_internal("override-bulletin-gate"))

    def test_the_real_bulletin_card_is_untouched(self):
        # The card that actually greens on a Friday send must stay carded — the
        # inversion _RETIRED's docstring warns about is silencing the wrong id.
        self.assertFalse(hc.is_internal("override_bulletin"))
        self.assertFalse(hc.is_internal("override-bulletin"))

    def test_the_handle_still_resolves_for_a_hand_rerun(self):
        # Not-a-CARD is not not-a-REPORT-ID: `lucy rerun override_bulletin_gate`
        # has to keep working, which means the schedule_config entry stays.
        from automations.day_orchestrator import registry
        cfg = registry.load_config()
        self.assertIn("override_bulletin_gate", cfg.raw.get("reports", {}))


if __name__ == "__main__":
    unittest.main()
