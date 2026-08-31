"""Two rows sharing a name is a refusal, not a coin flip.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.headshots.test_rep_row_ambiguity

WHY (2026-08-31). _rep_row returned `rows.first` whenever anything matched. What
callers do with that row is open Set Status and GENERATE A BUNDLE — nine
documents mailed, no unsend — so picking one of two same-named reps is picking
whose contract goes to whom. The OwnerVille directory really does hold twins:
two Nathan Sanchez that day, different people, different emails, four weeks
apart in start date. The ADD path already refused that case loudly. The row
lookup, one function away, took the first and said nothing.
"""
from __future__ import annotations

import re
import unittest

from automations.headshots import ov_upload as ov


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def count(self):
        return len(self._rows)

    @property
    def first(self):
        return self._rows[0]

    def filter(self, has_text=None):
        pat = has_text if isinstance(has_text, re.Pattern) else re.compile(
            re.escape(str(has_text)), re.I)
        return _Rows([r for r in self._rows if pat.search(r)])


class _Page:
    def __init__(self, rows):
        self._rows = rows

    def locator(self, _sel):
        return _Rows(self._rows)


class RepRowAmbiguityTest(unittest.TestCase):

    TWINS = ["Nathan Sanchez (9401912) RES-AT&T",
             "Nathan Sanchez (9447431) RES-AT&T"]

    def test_one_row_is_still_a_match(self):
        page = _Page(["Nathan Sanchez (9447431) RES-AT&T", "Ana Lopez (1) X"])
        self.assertIsNotNone(ov._rep_row(page, "Nathan Sanchez"))

    def test_two_rows_without_an_id_refuse(self):
        page = _Page(self.TWINS)
        self.assertIsNone(ov._rep_row(page, "Nathan Sanchez"),
                          "picking one of two would decide whose contract "
                          "goes to whom")

    def test_two_rows_with_an_id_take_that_one(self):
        page = _Page(self.TWINS)
        row = ov._rep_row(page, "Nathan Sanchez", employee_id="9447431")
        self.assertIsNotNone(row)
        self.assertIn("9447431", row)

    def test_an_id_matching_neither_row_refuses(self):
        page = _Page(self.TWINS)
        self.assertIsNone(
            ov._rep_row(page, "Nathan Sanchez", employee_id="1234567"))

    def test_no_row_is_still_no_row(self):
        self.assertIsNone(ov._rep_row(_Page(["Ana Lopez (1) X"]), "Bo Diaz"))


if __name__ == "__main__":
    unittest.main()
