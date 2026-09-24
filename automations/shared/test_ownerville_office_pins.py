"""Shealey Miller's knocks are Angel Padilla's office 23858 — never his 22400.

Angel owns two ownerville offices under the same name; a name search takes the
first row. The pin makes the search go by number and the identity check refuse
the other office. Offline: the page is a stub returning a canned label.
"""
import unittest

from automations.captainship_night_knocks import owners
from automations.rashad_metrics import knocks_pull as KP
from automations.shared import ownerville_office_pins as P
from automations.rashad_metrics.test_impersonation_assert import _Page


class Pins(unittest.TestCase):
    def test_shealey_is_pinned_to_23858(self):
        self.assertEqual(P.pinned_office("Shealey Miller"), "23858")
        self.assertEqual(P.pinned_office("  shealey   MILLER "), "23858")

    def test_a_normal_owner_is_not_pinned(self):
        self.assertIsNone(P.pinned_office("Angel Padilla"))
        self.assertIsNone(P.pinned_office("Nuri Burgos"))

    def test_label_matches_the_number_as_a_whole_token(self):
        self.assertTrue(P.label_is_office(
            "Angel Padilla (23858 - Azul Connections Inc 2nd)", "23858"))
        self.assertFalse(P.label_is_office(
            "Angel Padilla (22400 - Azul Connections Inc)", "23858"))
        self.assertFalse(P.label_is_office("X (123858 - Y)", "23858"))


class AssertImpersonatingPinned(unittest.TestCase):
    def test_the_pinned_office_passes(self):
        page = _Page("Angel Padilla (23858 - Azul Connections Inc 2nd)")
        KP.assert_impersonating(page, "RQ", "Shealey Miller", {},
                                verbose=False)

    def test_the_owners_other_office_raises(self):
        """Same owner name, wrong office — the case a name check can't see."""
        page = _Page("Angel Padilla (22400 - Azul Connections Inc)")
        with self.assertRaises(RuntimeError) as cm:
            KP.assert_impersonating(page, "RQ", "Shealey Miller", {},
                                    verbose=False)
        self.assertIn("23858", str(cm.exception))


class NightMailRecipients(unittest.TestCase):
    def test_shealey_angel_and_eve(self):
        self.assertEqual(owners.recipients("Shealey Miller"),
                         ["miller10xbusiness@gmail.com",
                          "padilla10x2001@gmail.com",
                          owners.ALWAYS_CC])

    def test_a_normal_office_is_still_owner_plus_eve(self):
        self.assertEqual(owners.recipients("Nuri Burgos"),
                         ["nuri@22select.com", owners.ALWAYS_CC])


if __name__ == "__main__":
    unittest.main()
