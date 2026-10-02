"""Tests for the auto-set SPECIAL marker (`markers.set_marker` + its run.py call).

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.override_bulletin.test_special_marker

WHAT THESE GUARD (2026-10-02). run.py passed `write_week`'s return value — the
column LETTER "G" — to set_marker, which expects a 0-based index and died on
`"G" % 26`. run.py's try/except turned that into one quiet "auto-marker skipped"
line, so from 2026-08-01 on no special period ever got its red marker, and
without a marker the special is never placed: P8-2026 (WE 8.16.26) and P9-2026
(WE 9.13.26, Colten $33,745.60 + Carlos $272.55) both had to be fixed by hand.
"""
from __future__ import annotations

import inspect
import unittest

from automations.override_bulletin import markers as M
from automations.override_bulletin import run as R


class _WS:
    title = "Copy of Org Overrides Ongoing Report"

    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


def _tab():
    rows = [["ALL ORG OVERRIDES", "9.27.26", "9.20.26", "9.13.26"]]
    rows += [["x", "", "", ""] for _ in range(5)]
    rows.append(["Special Overrides", "", "", "P8-2026"])   # row 7 = annotation row
    return _WS(rows)


class SetMarkerColumn(unittest.TestCase):
    def test_index_and_letter_land_on_the_same_cell(self):
        ws = _tab()
        self.assertEqual(M.set_marker(ws, M.SPECIAL, "P9-2026", 3), "D7")
        self.assertEqual(M.set_marker(ws, M.SPECIAL, "P9-2026", "D"), "D7")

    def test_run_passes_the_column_index_not_write_weeks_letter(self):
        src = inspect.getsource(R.run)
        call = src[src.index("M.set_marker(ws, M.SPECIAL"):]
        call = call[:call.index(")") + 1]
        self.assertNotIn("prior, col,", call)
        self.assertIn("week_col", src[src.index("M.set_marker(ws, M.SPECIAL"):][:200])


if __name__ == "__main__":
    unittest.main()
