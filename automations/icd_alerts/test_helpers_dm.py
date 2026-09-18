"""The person who walks to the machine has to be told about the machine.

Megan, 2026-09-18: "For khalil's alerts it should include Francia in the DM".

Francia Olivares ran every sign-in step on Khalil's computer for two days --
the boot-job repair, the SaraPlus passcode window, all of it -- while the
alerts that prompted each one went to Khalil and to Megan and Eve. The one
person who could act was the only one not being told.

KEYED SEPARATELY FROM AlertOffice on purpose: khalil-nds comes from the
SIGN-UP TAB, not the code table, and all_offices() merges the tab then the
code table with CODE WINNING. A code row added just to carry a helper would
have silently overridden whatever the owner typed into the form -- which cost
Aya an hour of her Saturday on 2026-09-17.
"""
from __future__ import annotations

import unittest

from automations.icd_alerts import offices as O


class HelpersAreLookedUpByOfficeKeyTest(unittest.TestCase):
    def test_khalil_has_francia(self):
        self.assertIn("U0543NQEWMD", O.helpers_for("khalil"))

    def test_the_live_enrolment_key_has_her_too(self):
        """He installed as khalil-nds; that is the key the faults carry, and
        it is the one the DM actually looks up."""
        self.assertIn("U0543NQEWMD", O.helpers_for("khalil-nds"))

    def test_other_offices_have_none(self):
        for k in ("kash", "cyrus", "aya", "roshan", "ryan"):
            self.assertEqual(O.helpers_for(k), ())

    def test_an_unknown_office_is_empty_not_an_error(self):
        self.assertEqual(O.helpers_for("nobody"), ())
        self.assertEqual(O.helpers_for(""), ())
        self.assertEqual(O.helpers_for(None), ())

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(O.helpers_for("KHALIL-NDS"), O.helpers_for("khalil-nds"))


class HelpersDoNotReplaceTheOwnerTest(unittest.TestCase):
    def test_a_helper_is_not_on_the_office_record(self):
        """It must not be a field that a code row could carry, or adding one
        would shadow a form answer."""
        o = O.get("khalil-nds")
        self.assertFalse(hasattr(o, "helpers"),
                         "helpers on AlertOffice would reintroduce the "
                         "code-shadows-the-form bug")

    def test_the_office_still_has_its_own_owner_id(self):
        o = O.get("khalil-nds")
        self.assertTrue(getattr(o, "slack_user_id", ""),
                        "the owner is told about their own office too")


if __name__ == "__main__":
    unittest.main()
