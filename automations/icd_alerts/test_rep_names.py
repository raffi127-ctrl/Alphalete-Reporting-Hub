"""The spelling tab: what it fixes, and what it must never touch.

The one that matters is the LAST test. A name fix that reached the relay's
state keys would read as a brand-new rep with a count of zero and re-announce
her whole day in front of her office -- which is the exact failure the baseline
and only-ever-up rules exist to prevent, arriving through a different door.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.icd_alerts import post, rep_names as RN


class FakeTab:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


class FakeBook:
    def __init__(self, rows=None, raise_=False):
        self._rows = rows or []
        self._raise = raise_

    def worksheet(self, title):
        if self._raise or title != RN.TAB:
            raise RuntimeError("no such tab: %s" % title)
        return FakeTab([RN.HEADERS] + self._rows)


ROWS = [
    ["kash", "CALLISA FLYTHE", "Callista Flythe", "Megan", "SaraPlus typo"],
    ["Cyrus", "  jordan  banks ", "Jordan Banks-Okoro", "Megan", ""],
    ["kash", "NOBODY", "", "Megan", "no replacement -- ignore"],
    ["", "ORPHAN NAME", "Somebody", "Megan", "no office -- ignore"],
]


class Loading(unittest.TestCase):

    def test_reads_the_rows_it_should(self):
        fixes = RN.load(FakeBook(ROWS))
        self.assertEqual(fixes[("kash", "CALLISA FLYTHE")], "Callista Flythe")
        # a person types these: case and inside spacing are forgiven
        self.assertEqual(fixes[("cyrus", "JORDAN BANKS")], "Jordan Banks-Okoro")

    def test_a_half_filled_row_is_ignored(self):
        fixes = RN.load(FakeBook(ROWS))
        # Renaming a rep in an office nobody meant is worse than not renaming
        # her, so a row missing its office or its replacement does nothing.
        self.assertNotIn(("kash", "NOBODY"), fixes)
        self.assertEqual([k for k in fixes if k[1] == "ORPHAN NAME"], [])

    def test_no_tab_is_not_a_failure(self):
        # An office must never lose its alerts to a missing spelling tab.
        self.assertEqual(RN.load(FakeBook(raise_=True)), {})


class Resolving(unittest.TestCase):

    def test_an_office_with_no_fixes_gets_none(self):
        # None, not an identity function -- the caller's own default
        # title-cases, and a no-op would silently replace it.
        self.assertIsNone(RN.resolver(RN.load(FakeBook(ROWS)), "jamis"))

    def test_one_office_cannot_rename_anothers_rep(self):
        fixes = RN.load(FakeBook(
            ROWS + [["jamis", "CALLISA FLYTHE", "Someone Else", "", ""]]))
        self.assertEqual(RN.resolver(fixes, "kash")("CALLISA FLYTHE"),
                         "Callista Flythe")
        self.assertEqual(RN.resolver(fixes, "jamis")("CALLISA FLYTHE"),
                         "Someone Else")

    def test_a_rep_with_no_fix_is_left_alone(self):
        show = RN.resolver(RN.load(FakeBook(ROWS)), "kash")
        self.assertEqual(show("CALEB RICHARDS"), "CALEB RICHARDS")


class WhatGoesOut(unittest.TestCase):

    def _show(self, office="kash"):
        return RN.resolver(RN.load(FakeBook(ROWS)), office)

    def test_the_credit_check_line_uses_the_office_spelling(self):
        lines, _merged, _base = post.decide(
            {"CALLISA FLYTHE": 2}, {"CALLISA FLYTHE": 1}, self._show())
        self.assertEqual(
            lines, [":mag: Callista Flythe just ran 1 credit check (2 today)."])

    def test_an_unfixed_rep_still_gets_cased(self):
        lines, _m, _b = post.decide({"CALEB RICHARDS": 1}, {}, self._show())
        self.assertIn("Caleb Richards", lines[0])
        self.assertNotIn("CALEB RICHARDS", lines[0])

    def test_the_hype_line_uses_it_too(self):
        from automations.shared import sale_hype as H
        said = H.hype(self._show()("CALLISA FLYTHE"),
                      {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0},
                      dt.date(2026, 9, 14))
        self.assertTrue(said.startswith("Callista "), said)

    def test_no_resolver_behaves_exactly_as_before(self):
        self.assertEqual(post.decide({"A B": 2}, {"A B": 1}),
                         post.decide({"A B": 2}, {"A B": 1}, None))

    def test_the_fix_NEVER_reaches_the_state_keys(self):
        # THE ONE THAT MATTERS. 'Last Posted' is keyed by SaraPlus's spelling.
        # If a fix leaked into it, the next tick would see a rep it had never
        # heard of, at zero, and announce her whole day over again.
        _lines, merged, _base = post.decide(
            {"CALLISA FLYTHE": 2}, {"CALLISA FLYTHE": 1}, self._show())
        self.assertEqual(merged, {"CALLISA FLYTHE": 2})
        self.assertNotIn("Callista Flythe", merged)


if __name__ == "__main__":
    unittest.main()
