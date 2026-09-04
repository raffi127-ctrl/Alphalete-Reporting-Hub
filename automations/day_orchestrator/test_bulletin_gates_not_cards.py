"""Neither bulletin's review-gate HANDLE may get its own Hub card.

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

`dd_bulletin_gate` is the same dupe a day earlier in the week — review_gate
publishes under `dd_bulletin`, so its 12 rows are all hand-runs too. It was
quieter only because it registered "on-demand" rather than weekly, so it never
claimed to be DUE. It came out in the same pass, with one difference worth
keeping straight: the DD card did NOT already carry the gate buttons, so the
stub was the only Hub path to "post the DD gate". Those two buttons were added
to the dd-bulletin card in the same commit — retire the stub, keep the
capability. That is what the last test here checks.

Both spellings are listed for the reason owner_showdown documents: sync() keys
on the report_id, sync_launchd_system() derives the kebab id from the plist
label, and a row deleted while only one door is shut comes straight back.
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator import hub_coverage as hc


GATES = ("override_bulletin_gate", "dd_bulletin_gate")


class TheGateHandlesAreNotReports(unittest.TestCase):

    def test_both_spellings_are_declared_internal(self):
        # Underscore = the scheduler door; kebab = the plist door.
        for gate in GATES:
            self.assertTrue(hc.is_internal(gate), gate)
            self.assertTrue(hc.is_internal(gate.replace("_", "-")), gate)

    def test_the_real_bulletin_cards_are_untouched(self):
        # The cards that actually green on a send must stay carded — the
        # inversion _RETIRED's docstring warns about is silencing the wrong id.
        for card in ("override_bulletin", "override-bulletin",
                     "dd_bulletin", "dd-bulletin"):
            self.assertFalse(hc.is_internal(card), card)

    def test_the_handles_still_resolve_for_a_hand_rerun(self):
        # Not-a-CARD is not not-a-REPORT-ID: `lucy rerun <gate>` has to keep
        # working, which means the schedule_config entries stay.
        from automations.day_orchestrator import registry
        reports = registry.load_config().raw.get("reports", {})
        for gate in GATES:
            self.assertIn(gate, reports)

    def test_the_dd_card_absorbed_the_stub_s_capability(self):
        # The DD card had no gate buttons of its own, so retiring the stub
        # without these would have taken "post the DD gate" off the Hub.
        from automations import hub_cards
        card = next(c for c in hub_cards.AUTOMATED_REPORTS
                    if c.get("id") == "dd-bulletin")
        gate_actions = [a for a in card["actions"]
                        if a["module"] == "automations.override_bulletin.review_gate"]
        self.assertEqual([["--post"], ["--check", "--send", "--distro"]],
                         [a["args_fn"]() for a in gate_actions])


if __name__ == "__main__":
    unittest.main()
