from __future__ import annotations

import unittest

from automations.captainship_night_knocks.addresses import (
    SPLIT_STATES, resolve,
)


class SingleZoneStates(unittest.TestCase):
    def test_california_is_pacific_from_the_state_alone(self):
        r = resolve("Fresno", "CA")
        self.assertEqual(r.zone, "America/Los_Angeles")
        self.assertEqual(r.confidence, "state")

    def test_arizona_gets_its_own_zone_not_denvers(self):
        """Phoenix skips DST — filing it under Denver is an hour wrong all
        summer."""
        self.assertEqual(resolve("Mesa", "AZ").zone, "America/Phoenix")

    def test_case_and_space_do_not_matter(self):
        self.assertEqual(resolve("  Fresno ", " ca ").zone,
                         "America/Los_Angeles")


class SplitStatesRefuseToGuess(unittest.TestCase):
    def test_an_unknown_texas_city_is_not_assumed_central(self):
        r = resolve("Nowhereville", "TX")
        self.assertIsNone(r.zone)
        self.assertIn("split", r.note)

    def test_every_split_state_refuses_an_unknown_city(self):
        for st in SPLIT_STATES:
            self.assertIsNone(resolve("Unheard Of", st).zone, st)

    def test_a_confirmed_city_answers(self):
        self.assertEqual(resolve("Lubbock", "TX").zone, "America/Chicago")
        self.assertEqual(resolve("lubbock", "TX").confidence, "city")

    def test_el_paso_is_mountain_not_central(self):
        """The one Texas answer that is not Central."""
        self.assertEqual(resolve("El Paso", "TX").zone, "America/Denver")

    def test_indianapolis_keeps_its_own_iana_name(self):
        self.assertEqual(resolve("Indianapolis", "IN").zone,
                         "America/Indiana/Indianapolis")


class MissingData(unittest.TestCase):
    def test_no_state_is_unknown_not_a_crash(self):
        self.assertIsNone(resolve("Somewhere", "").zone)

    def test_unlisted_state_says_so(self):
        r = resolve("Honolulu", "HI")
        self.assertIsNone(r.zone)
        self.assertIn("not in the table", r.note)


class SeededOfficesRoundTrip(unittest.TestCase):
    """The eleven harvested 2026-08-25 must resolve to what was committed."""

    CASES = [
        ("Lubbock", "TX", "America/Chicago"),
        ("Indianapolis", "IN", "America/Indiana/Indianapolis"),
        ("Tyler", "TX", "America/Chicago"),
        ("Southfield", "MI", "America/Detroit"),
        ("Fort Worth", "TX", "America/Chicago"),
        ("Corpus Christi", "TX", "America/Chicago"),
        ("Austin", "TX", "America/Chicago"),
        ("San Antonio", "TX", "America/Chicago"),
        ("Dallas", "TX", "America/Chicago"),
        ("Wilkes-Barre", "PA", "America/New_York"),
    ]

    def test_all_of_them(self):
        for city, st, want in self.CASES:
            self.assertEqual(resolve(city, st).zone, want, f"{city}, {st}")


if __name__ == "__main__":
    unittest.main()
