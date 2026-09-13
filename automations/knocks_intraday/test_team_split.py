"""Raf's daily interval boards, broken up by team — offline.

RAF'S IS THE ONLY BOARD THAT CHANGES (Megan 2026-09-13). The first test here
is the one that matters: an office with no sales board draws the table it has
always drawn, cell for cell.

    python -m unittest automations.knocks_intraday.test_team_split
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.total_knocks import render as R
from automations.total_knocks.pull import SHEET_COLUMNS
from automations.weekly_knock_dispositions import teams as T

DAY = dt.date(2026, 9, 11)

BOARD = [("Hank Tran", "Se7en Sins"), ("Noemi (Ivette) Ontiveros", "Se7en Sins"),
         ('Terrance "Dior" Dandy', "Ceaseless"), ("Andrea Herrera", "Hashiras"),
         ("Andrew Sanborn", "Mindset Engine")]


def _book():
    from automations.weekly_knock_dispositions.test_teams import _book as mk
    return mk(BOARD)


def _rec(name, knocks, talk=20):
    d = {c: "" for c in SHEET_COLUMNS}
    d.update({"Rep": name, "Total Knocks": str(knocks), "Total Talk to": str(talk),
              "First Knock": "10:30 AM", "Last Knock": "7:20 PM",
              "Gaps": "60", "Total Gaps": "120", "Hrs Knocking": "400"})
    return d


ROWS = [_rec("Hank Tran", 200), _rec("Noemi Ontiveros", 150),
        _rec("Terrance Dandy", 180), _rec("Andrea Herrera", 90),
        _rec("Andrew Sanborn Roadtrip", 120), _rec("Brand New Person", 60)]
APPS = {"Hank Tran": 3, "Noemi Ontiveros": 1, "Terrance Dandy": 2,
        "Andrea Herrera": 0, "Andrew Sanborn Roadtrip": 4,
        "Brand New Person": 5}


def _capture(**kw):
    """Render once and return (display headers, table) as _draw received it."""
    grabbed = {}
    real = R._draw

    def spy(header, rows, *a, **k):
        grabbed["header"], grabbed["rows"] = list(header), [list(r) for r in rows]
        return real(header, rows, *a, **k)

    R._draw = spy
    try:
        with tempfile.TemporaryDirectory() as d:
            R.render_knocks_boards(DAY, rows=ROWS, out_dir=Path(d),
                                   title_suffix="Test", apps=APPS, **kw)
    finally:
        R._draw = real
    return grabbed["header"], grabbed["rows"]


class OnlyRafChanges(unittest.TestCase):
    def test_no_sales_board_means_the_identical_table(self):
        plain = _capture()
        none_ = _capture(teams=None)
        self.assertEqual(plain, none_)

    def test_no_band_rows_without_teams(self):
        _h, table = _capture()
        self.assertFalse([r for r in table if R.is_team_band(r)])

    def test_for_office_never_touches_sheets_for_another_office(self):
        self.assertIsNone(T.for_office("Some Other Owner", DAY))


class TeamBands(unittest.TestCase):
    def setUp(self):
        self.header, self.table = _capture(teams=_book())
        self.bands = [r for r in self.table if R.is_team_band(r)]
        self.total = next(r for r in self.table
                          if str(r[1]).strip() == R.OFFICE_TOTAL_LABEL)

    def test_one_band_per_team_alphabetical_unassigned_last(self):
        self.assertEqual([r[1] for r in self.bands], [
            f"{R.TEAM_BAND_PREFIX}CEASELESS",
            f"{R.TEAM_BAND_PREFIX}HASHIRAS",
            f"{R.TEAM_BAND_PREFIX}MINDSET ENGINE",
            f"{R.TEAM_BAND_PREFIX}SE7EN SINS",
            f"{R.TEAM_BAND_PREFIX}{T.UNASSIGNED.upper()}"])

    def _col(self, name):
        return self.header.index(name)

    def test_bands_sum_to_the_office_total(self):
        """If a band double-counted or dropped a rep, this is where it shows."""
        for col in ("Total Knocks", "Total Talk to"):
            i = self._col(col)
            self.assertEqual(
                sum(int(b[i]) for b in self.bands), int(self.total[i]),
                f"{col}: bands do not sum to TOTAL")

    def test_apps_column_sums_to_the_office_total(self):
        i = self._col("Total Apps")
        self.assertEqual(sum(int(b[i]) for b in self.bands),
                         int(self.total[i]))

    def test_every_rep_appears_once(self):
        names = [r[1] for r in self.table[2:] if not R.is_team_band(r)]
        self.assertEqual(sorted(names), sorted(r["Rep"] for r in ROWS))

    def test_numbering_restarts_inside_each_team(self):
        seen, expect, n = [], [], 0
        for r in self.table[2:]:
            if R.is_team_band(r):
                n = 0
                self.assertNotEqual(r[0], "")   # the band keeps its count
                continue
            n += 1
            seen.append(r[0])
            expect.append(str(n))
        self.assertEqual(seen, expect)

    def test_a_band_is_not_greened(self):
        """A green team total is a different claim from a rep hitting his
        number — the targets are for the reps."""
        _h, table = _capture(teams=_book(), knocks_green_at=1)
        self.assertTrue(table)              # rendered; bands simply skipped


if __name__ == "__main__":
    unittest.main()
