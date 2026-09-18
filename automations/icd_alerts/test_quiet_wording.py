"""A nudge that gets the basics wrong is one people stop reading.

2026-09-18. Roshan's office went quiet and the ops room said:

    Nothing is lost: SaraPlus is cumulative, so whatever it missed arrives
    when the laptop is back online.

Roshan sells BOX and reads My Service Cloud -- her office has never touched
SaraPlus -- and she runs an iMac. Megan: "ROshan has an Imac so shouldn't be
logged out". Two hardcoded words, written when every office was AT&T on a
laptop, and both wrong for her.

The same shape as every other non-AT&T bug in this codebase: a campaign that
is not `att` falling through a path written as though it were.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import post as P


class _Office:
    def __init__(self, campaign):
        self.campaign = campaign


class TheRightSystemIsNamedTest(unittest.TestCase):
    def test_box_offices_are_told_about_service_cloud(self):
        self.assertEqual(P.sales_system_for(_Office("b2b_box")),
                         "My Service Cloud")

    def test_energy_is_not_saraplus_either(self):
        self.assertEqual(P.sales_system_for(_Office("energy")),
                         "My Service Cloud")

    def test_att_offices_are_told_about_saraplus(self):
        for c in ("att", "nds", "b2b_att"):
            self.assertEqual(P.sales_system_for(_Office(c)), "SaraPlus")

    def test_an_unknown_campaign_does_not_crash(self):
        self.assertIn(P.sales_system_for(_Office("")), ("SaraPlus",
                                                        "My Service Cloud"))
        self.assertTrue(P.sales_system_for(None))


class TheRightBoxIsNamedTest(unittest.TestCase):
    def test_a_desktop_is_not_told_to_open_its_lid(self):
        w = P.machine_words(laptop=False)
        self.assertEqual(w["noun"], "computer")
        self.assertNotIn("lid", w["asleep"])
        self.assertNotIn("unplugged", w["power"])

    def test_a_laptop_still_gets_laptop_advice(self):
        w = P.machine_words(laptop=True)
        self.assertEqual(w["noun"], "laptop")
        self.assertIn("lid", w["asleep"])

    def test_the_default_is_the_desktop_wording(self):
        """It is the one that is never absurd -- 'may be switched off' is
        merely incomplete for a laptop owner, while 'leave the lid open'
        reads as a message meant for somebody else."""
        self.assertEqual(P.machine_words()["noun"], "computer")


class TheOwnerNudgeMatchesTheirMachineTest(unittest.TestCase):
    def setUp(self):
        self.q = {"office": "roshan", "label": "Roshan's Local Office",
                  "last": "9/18/2026 10:28:36",
                  "reason": "last checked in 9/18/2026 10:28:36"}

    def test_imac_owner_is_not_told_about_a_lid(self):
        got = P._nudge_text("Roshan", self.q, laptop=False)
        self.assertNotIn("lid", got)
        self.assertIn("mouse or keyboard", got)

    def test_laptop_owner_is(self):
        got = P._nudge_text("Cyrus", self.q, laptop=True)
        self.assertIn("lid", got)

    def test_it_still_says_when_it_stopped(self):
        self.assertIn("10:28:36", P._nudge_text("Roshan", self.q))


class LaptopLookupNeverCostsTheNudgeTest(unittest.TestCase):
    def test_a_failed_lookup_is_an_empty_set_not_a_crash(self):
        with mock.patch.object(P, "laptop_offices",
                               side_effect=RuntimeError("429")):
            self.assertEqual(P.laptop_keys(), set())


if __name__ == "__main__":
    unittest.main()
