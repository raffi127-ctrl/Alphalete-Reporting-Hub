"""The address parser, pinned. No browser — parse_address takes page text.

The ownerville half of harvest_zones cannot run here (no session on Windows),
which is exactly why the parsing lives in a function that takes a string.
"""
from __future__ import annotations

import unittest

from automations.captainship_night_knocks.harvest_zones import parse_address


class ParseAddress(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(
            parse_address("Company Information\nAlphalete\n"
                          "5217 82nd St\nLubbock, TX 79424\nPhone: ..."),
            {"city": "Lubbock", "state": "TX", "zip": "79424"})

    def test_hyphenated_city(self):
        """Wilkes-Barre is a real office, and the hyphen is the character most
        likely to break a lazier pattern."""
        self.assertEqual(parse_address("Wilkes-Barre, PA 18701")["city"],
                         "Wilkes-Barre")

    def test_two_word_city(self):
        self.assertEqual(parse_address("Corpus Christi, TX 78412")["city"],
                         "Corpus Christi")

    def test_zip_plus_four(self):
        self.assertEqual(parse_address("Austin, TX 78701-1234")["zip"], "78701")

    def test_lowercase_state_is_normalised(self):
        self.assertEqual(parse_address("Dallas, tx 75201")["state"], "TX")

    def test_no_address_returns_none(self):
        self.assertIsNone(parse_address("Company Information\nNo data."))

    def test_empty_is_none_not_a_crash(self):
        self.assertIsNone(parse_address(""))
        self.assertIsNone(parse_address(None))


if __name__ == "__main__":
    unittest.main()
