"""The removal rules' guard rails."""
from __future__ import annotations

import unittest

from automations.second_round_contacts import rules


class RemovalsHeldForAnOfficeThatMayNotMark(unittest.TestCase):
    """An office whose removals are on hold keeps its cards, in every mode.

    The removal rules all read the same shape -- no BOB, no offer, no start,
    so they were not brought on board -- and that is only true where the
    office marks. On 2026-11-23 Cyrus's account restored 0 of 91 while the
    same pass, same day, same reader, restored 27 for one office and 19 for
    another. One account reading empty next to two reading full is not proof
    the office hires nobody.
    """

    def test_nobody_is_held_now(self):
        """Megan, 2026-11-24: "as long as eve has rules in place you can
        remove", then "take cy live as well for removals". Cyrus Wade's
        hold is lifted -- OVERRULED, not answered: nothing established
        whether that office marks BOB. What protects them now is `decide`,
        not this list, and if cards come off their phone that should not
        have, this is the first place to look."""
        self.assertEqual(rules.HOLD_REMOVALS, {})
        self.assertEqual(rules.removals_held("Cyrus Wade"), "")

    def test_the_hold_still_works_if_somebody_is_put_back_on_it(self):
        """The list is empty, not deleted. A future office that reads empty
        next to two reading full can be held the same way."""
        rules.HOLD_REMOVALS["Test Office"] = "because"
        try:
            self.assertEqual(rules.removals_held("Test Office"), "because")
        finally:
            rules.HOLD_REMOVALS.pop("Test Office", None)

    def test_everybody_else_is_not_held(self):
        for owner in ("Rafael Hidalgo", "Omar Mohamad", "Hasan Salame"):
            self.assertEqual(rules.removals_held(owner), "",
                             "%s should not be held" % owner)

    def test_an_unknown_or_blank_owner_is_not_held(self):
        """A hold must never be the DEFAULT. Holding everybody the moment a
        name does not match would stop the whole job quietly."""
        self.assertEqual(rules.removals_held(""), "")
        self.assertEqual(rules.removals_held(None), "")
        self.assertEqual(rules.removals_held("Somebody New"), "")

    def test_the_name_is_matched_the_way_the_roster_spells_it(self):
        self.assertEqual(rules.removals_held("  Cyrus Wade  "),
                         rules.removals_held("Cyrus Wade"))

    def test_the_hold_does_not_change_what_the_rules_decide(self):
        """The hold is applied where the card is taken off, NOT inside
        decide(). A rule that stopped firing would also stop the state file
        recording why somebody would have gone, and the reason is the whole
        evidence for lifting the hold later."""
        import inspect
        self.assertNotIn("HOLD_REMOVALS", inspect.getsource(rules.decide))
