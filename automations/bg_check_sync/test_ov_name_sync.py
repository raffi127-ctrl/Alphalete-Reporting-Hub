"""What counts as "OwnerVille already matches Sterling" — the part that can be
tested without a browser, which is the part that decides whether anybody's OV
profile gets rewritten."""
from __future__ import annotations

import unittest

from automations.bg_check_sync.ov_name_sync import (
    OVCheck, _probes, identifies, matches, needs_edit, split_display, summarise,
)


def row(first, last, email="", status="Active"):
    return {"first": first, "last": last, "full": f"{first} {last}",
            "email": email, "status": status}


class SplitTests(unittest.TestCase):

    def test_first_last(self):
        self.assertEqual(split_display("Bianca Mendez"), ("Bianca", "Mendez"))

    def test_last_comma_first(self):
        self.assertEqual(split_display("Mendez, Bianca"), ("Bianca", "Mendez"))

    def test_the_ov_id_is_stripped(self):
        self.assertEqual(split_display("Bianca Mendez (9445955)"),
                         ("Bianca", "Mendez"))

    def test_two_word_surname_stays_together(self):
        self.assertEqual(split_display("Berenice Monzon Martinez"),
                         ("Berenice", "Monzon Martinez"))


class MatchTests(unittest.TestCase):

    def test_exact_match(self):
        self.assertTrue(matches("Bianca Mendez", "Bianca", "Mendez"))

    def test_shouting_is_not_a_mismatch(self):
        self.assertTrue(matches("TAVAIESHA VASQUEZ", "Tavaiesha", "Vasquez"))

    def test_comma_form_is_not_a_mismatch(self):
        self.assertTrue(matches("Mendez, Bianca", "Bianca", "Mendez"))

    def test_two_word_surname_in_either_field_still_matches(self):
        self.assertTrue(matches("Monzon Martinez, Berenice",
                                "Berenice", "Monzon Martinez"))

    def test_a_nickname_is_a_mismatch(self):
        self.assertTrue(needs_edit("Nikki Valentine", "Shuminique", "Valentine"))

    def test_a_dropped_middle_name_is_a_mismatch(self):
        """Megan's bar is exact — Sterling's spelling wins."""
        self.assertTrue(needs_edit("Erica Glenn", "Erica", "Glenn Jackson"))

    def test_a_blank_ov_name_is_not_something_to_edit(self):
        """Nothing read means nothing known — refuse, don't overwrite."""
        self.assertFalse(needs_edit("", "Shuminique", "Valentine"))


class IdentityTests(unittest.TestCase):
    """Which OwnerVille row is this person — proved live 2026-08-26."""

    NIKKI = OVCheck("Nikki Valentine", "Shuminique", "Valentine",
                    email="Shuminiquevalentine@yahoo.com")

    def test_email_is_proof(self):
        self.assertEqual(
            identifies(row("Bianca", "Mendez", "berenicemendez11@gmail.com"),
                       OVCheck("Bianca Mendez", "Bianca", "Mendez",
                               email="berenicemendez11@gmail.com")),
            "email")

    def test_ov_holding_the_legal_name_is_still_our_person(self):
        """OwnerVille has 'Shuminique Valentine' under a different address —
        the checklist is the wrong one there, not OV."""
        self.assertEqual(
            identifies(row("Shuminique", "Valentine", "Nikkivalentine93@yahoo.com"),
                       self.NIKKI),
            "name")

    def test_a_dropped_second_surname_still_identifies(self):
        self.assertEqual(
            identifies(row("Yajaira", "Hernandez"),
                       OVCheck("Yajaira Hernandez", "Yajaira", "Hernandez Rodriguez")),
            "name")

    def test_a_near_twin_is_not_our_person(self):
        self.assertEqual(
            identifies(row("Carolina", "Haggerty"),
                       OVCheck("Carol Pena", "Carol", "Peña Contreras")),
            "")

    def test_a_shared_first_name_alone_is_not_enough(self):
        self.assertEqual(
            identifies(row("Carolina", "Martinez"),
                       OVCheck("Carolina Garza", "Carolina", "Garza Martinez")),
            "name")
        self.assertEqual(
            identifies(row("Carol", "Pena"),
                       OVCheck("Carolina Haggerty", "Carolina", "Haggerty")),
            "")


class ProbeTests(unittest.TestCase):
    """One token at a time — 'Carol Pena' filters that table to zero."""

    def test_probes_are_all_single_tokens(self):
        for probe in _probes(OVCheck("Carol Pena", "Carol", "Peña Contreras",
                                     email="carolpena0718@gmail.com")):
            self.assertNotIn(" ", probe, f"{probe!r} is not a single token")

    def test_email_is_tried_first(self):
        probes = _probes(OVCheck("Carol Pena", "Carol", "Peña Contreras",
                                 email="carolpena0718@gmail.com"))
        self.assertEqual(probes[0], "carolpena0718@gmail.com")

    def test_surname_before_first_name(self):
        probes = _probes(OVCheck("Carol Pena", "Carol", "Peña Contreras"))
        self.assertLess(probes.index("Pena"), probes.index("Carol"))

    def test_the_legal_name_is_probed_too(self):
        """OwnerVille may only know them by the name Sterling ran."""
        check = OVCheck("Nikki Valentine", "Shuminique", "Valentine")
        probes = [p.lower() for p in _probes(check)]
        self.assertIn("shuminique", probes)


class AccentTests(unittest.TestCase):
    """Half these surnames carry an accent; an ASCII strip breaks them."""

    def test_an_accented_name_matches_itself(self):
        self.assertTrue(matches("Guadalupe Cruz Jiménez", "Guadalupe", "Cruz Jiménez"))
        self.assertFalse(needs_edit("Guadalupe Cruz Jiménez", "Guadalupe",
                                    "Cruz Jiménez"))

    def test_the_accented_part_survives_the_split(self):
        self.assertEqual(split_display("Thais Fernández Salazar"),
                         ("Thais", "Fernández Salazar"))

    def test_an_accent_alone_is_not_a_mismatch(self):
        """'Pena' and 'Peña' are the same surname spelled two ways."""
        self.assertFalse(needs_edit("Carol Peña", "Carol", "Pena"))

    def test_a_real_difference_still_shows(self):
        self.assertTrue(needs_edit("Carol Pena", "Carol", "Peña Contreras"))


class SummaryTests(unittest.TestCase):

    def test_counts_by_action(self):
        rs = [OVCheck("A", "A", "A", action="match"),
              OVCheck("B", "B", "B", action="edited"),
              OVCheck("C", "C", "C", action="refused"),
              OVCheck("D", "D", "D", action="refused")]
        self.assertEqual(summarise(rs), "1 edited, 1 match, 2 refused")

    def test_empty_is_said_plainly(self):
        self.assertEqual(summarise([]), "nothing to do")


if __name__ == "__main__":
    unittest.main()
