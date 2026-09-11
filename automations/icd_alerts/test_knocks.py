"""Offline tests for the OwnerVille grid read. No browser, no network.

The stub page returns what the real one returns -- a header list and a list of
cell lists -- so these pin the part that turns a DataTables grid into rows: the
bit that has silently published 2 reps of 22 elsewhere in this repo.
"""
from __future__ import annotations

import unittest

from automations.shared import ownerville_knocks as K


class _Page:
    """The two evaluate() shapes read_rows depends on, and nothing else."""

    def __init__(self, headers, rows):
        self.headers, self.rows = headers, rows

    def wait_for_function(self, *a, **kw):
        return None

    def wait_for_timeout(self, *a, **kw):
        return None

    def evaluate(self, script, *args):
        if "thead" in script:
            return list(self.headers)
        if "_processing" in script:
            return len(self.rows)
        if "tbody tr" in script:
            return [list(r) for r in self.rows]
        return []


class ReadRowsTests(unittest.TestCase):
    HEADERS = ["Rep", "Total Knocks", "No answer", "Sale"]

    def test_rows_are_keyed_by_the_grids_own_headers(self):
        page = _Page(self.HEADERS, [["Ana Griffin", "42", "30", "2"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows, [{"rep": "Ana Griffin", "total knocks": "42",
                                 "no answer": "30", "sale": "2"}])

    def test_blank_rows_are_dropped(self):
        """DataTables renders a 'no data available' row that is not a rep."""
        page = _Page(self.HEADERS, [["", "", "", ""],
                                    ["Ian Rodriguez", "10", "8", "1"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rep"], "Ian Rodriguez")

    def test_an_empty_day_is_rows_not_an_error(self):
        """Nobody has knocked yet is a real answer every single morning."""
        page = _Page(self.HEADERS, [])
        self.assertEqual(K.read_rows(page, log=lambda *_: None), [])

    def test_a_grid_that_never_built_is_an_error_not_an_empty_day(self):
        """No headers means the page is not the grid -- almost always a
        sign-in that did not go through. Reporting it as a quiet day is how an
        office silently stops having a board."""
        page = _Page([], [])
        with self.assertRaises(K.OwnervilleError):
            K.read_rows(page, log=lambda *_: None)

    def test_extra_cells_beyond_the_headers_do_not_crash(self):
        page = _Page(self.HEADERS, [["Ana", "1", "2", "3", "surprise"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows[0]["sale"], "3")

    def test_short_rows_do_not_crash(self):
        page = _Page(self.HEADERS, [["Ana", "1"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows[0], {"rep": "Ana", "total knocks": "1"})

    def test_headers_are_normalised_so_spacing_changes_do_not_break_us(self):
        page = _Page(["Rep", "Total   Knocks "], [["Ana", "5"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertIn("total knocks", rows[0])


class HeaderIndexTests(unittest.TestCase):
    def test_index_maps_normalised_header_to_position(self):
        page = _Page(["Rep", "Total Knocks", "Sale"], [])
        self.assertEqual(K.header_index(page),
                         {"rep": 0, "total knocks": 1, "sale": 2})

    def test_missing_table_yields_an_empty_index(self):
        self.assertEqual(K.header_index(_Page([], [])), {})


if __name__ == "__main__":
    unittest.main()
