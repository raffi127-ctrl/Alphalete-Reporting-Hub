"""A name we don't know must not be answered as a PERMISSIONS gap.

Run:  PYTHONPATH=. .venv/Scripts/python.exe -m unittest \
          automations.knocks_request.test_unknown_office

WHAT THIS GUARDS (2026-08-31). `knocks Frank Castillo` answered ":lock: that
office isn't on the Ownerville account … It's a permissions gap, not a typo."
There is no office called Frank Castillo: ownerville returns the SAME "not
found in ownerville" for a misspelling as for an office nobody granted access
to, so the confident "not a typo" was asserted about a name that was one. The
roster has Francisco Castillo, and nobody chased it because the answer sent
them to ask for Office Access instead.

The contract:

  name on the roster + not found in ownerville  →  permissions gap (unchanged)
  name NOT on the roster, close match exists    →  "did you mean …?"
  name NOT on the roster, no close match        →  spelling-or-not-enrolled

The suggestion stays silent when two people share the surname: sending someone
another office's numbers is worse than sending nothing.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.knocks_request import service

ROSTER = ["Francisco Castillo", "Rafael Hidalgo", "Chan Park", "Isaiah Revelle"]


# The roster AND the alias table, both faked. `unknown_office` asks
# resolve_office whether a typed name maps to a real office, and resolve_office
# reads the LIVE ICD alias Sheet — so without this the test's answer changes
# whenever somebody adds an alias. That is exactly what happened: this file
# asserted "Frank Castillo" is a name nobody has, someone then did the right
# thing and added `Frank Castillo -> Francisco Castillo` to the alias sheet
# (the fix CLAUDE.md asks for), and the test started failing while the code was
# behaving correctly. A unit test must not depend on an editable Sheet.
ALIASES = {"frank castillo": "Francisco Castillo"}


def _fake_resolve(typed):
    return ALIASES.get(" ".join((typed or "").split()).lower(), typed)


def _with_roster(names):
    return mock.patch.multiple(
        service,
        known_office_names=lambda: list(names),
        resolve_office=_fake_resolve)


class UnknownOffice(unittest.TestCase):
    def test_a_roster_name_is_never_called_unknown(self):
        with _with_roster(ROSTER):
            self.assertFalse(service.unknown_office("Francisco Castillo"))

    def test_a_name_nobody_has_is_unknown(self):
        # A name that is on no roster and in no alias row.
        with _with_roster(ROSTER):
            self.assertTrue(service.unknown_office("Marvin Nonesuch"))

    def test_an_aliased_nickname_is_NOT_unknown(self):
        """THE ORIGINAL INCIDENT, now answered by the alias sheet.

        "Frank Castillo" got ":lock: that office isn't on the Ownerville
        account", a confident permissions answer about what was really a
        nickname. The fix was an alias row, not code — so once it exists the
        name RESOLVES and is not unknown at all. This pins that: adding the
        alias must make the question go away, not merely change which wrong
        answer is given."""
        with _with_roster(ROSTER):
            self.assertFalse(service.unknown_office("Frank Castillo"))

    def test_an_empty_roster_keeps_the_old_answer(self):
        """If the roster won't load we know nothing — and 'we know nothing' must
        not turn every real access gap into a spelling complaint."""
        with _with_roster([]):
            self.assertFalse(service.unknown_office("Marvin Nonesuch"))


class Suggestion(unittest.TestCase):
    def test_a_nickname_finds_the_legal_spelling(self):
        """THE CASE: 'Frank' is nowhere near 'Francisco' by character ratio —
        the shared surname is what carries it."""
        with _with_roster(ROSTER):
            self.assertEqual(service.suggest_office("Frank Castillo"),
                             "Francisco Castillo")

    def test_a_typo_finds_it_too(self):
        with _with_roster(ROSTER):
            self.assertEqual(service.suggest_office("Frnacisco Castillo"),
                             "Francisco Castillo")

    def test_two_people_share_a_surname_so_it_says_nothing(self):
        """Guessing between siblings sends someone the wrong office's board."""
        with _with_roster(ROSTER + ["Jordan Castillo"]):
            self.assertIsNone(service.suggest_office("Frank Castillo"))

    def test_a_name_like_nothing_on_the_roster_gets_no_hint(self):
        with _with_roster(ROSTER):
            self.assertIsNone(service.suggest_office("Zzz Nobody"))

    def test_the_alias_sheet_listing_one_person_twice_is_not_two_people(self):
        """The aliases feed this list, so the same person appears under several
        spellings — that must not read as an ambiguous surname."""
        with _with_roster(ROSTER + ["francisco castillo"]):
            self.assertEqual(service.suggest_office("Frank Castillo"),
                             "Francisco Castillo")


if __name__ == "__main__":
    unittest.main()
