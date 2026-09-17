"""What the knocks log writes, and the zero it used to eat.

THE BUG THIS FILE EXISTS FOR: append_day built each row with
`str(rec.get(c, "") or "")`, and `0 or ""` is `""`. Every genuine zero was
stored as an empty cell -- across 2540 logged rows the string "0" appeared
nowhere at all, while blanks were everywhere.

That collapsed a distinction the pull draws on purpose: COUNT_COLUMNS are
ints where blank means 0, but the Time Tracker pair stays BLANK when a rep
has no tracker row, because "did not clock in" and "stood still for zero
minutes" are different facts. After the blanking they looked identical.

    python -m unittest automations.icd_sales_board.test_knocks_log
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.icd_sales_board import knocks_log as KL


class TheCellHelper(unittest.TestCase):

    def test_a_real_zero_is_written_as_zero(self):
        self.assertEqual(KL._cell({"Sale": 0}, "Sale"), "0")

    def test_a_nonzero_count_is_unchanged(self):
        self.assertEqual(KL._cell({"Sale": 7}, "Sale"), "7")

    def test_an_absent_value_is_still_blank(self):
        """A rep with no Time Tracker row keeps Gaps blank -- that is the
        distinction the `or ""` destroyed, and it has to survive the fix."""
        self.assertEqual(KL._cell({}, "Gaps"), "")

    def test_an_empty_string_stays_empty(self):
        self.assertEqual(KL._cell({"Gaps": ""}, "Gaps"), "")

    def test_text_columns_pass_through(self):
        self.assertEqual(KL._cell({"First Knock": "2:21 PM"}, "First Knock"),
                         "2:21 PM")

    def test_zero_minutes_is_not_the_same_as_no_tracker_row(self):
        """The whole point, in one assertion."""
        self.assertNotEqual(KL._cell({"Total Gaps (min)": 0},
                                     "Total Gaps (min)"),
                            KL._cell({}, "Total Gaps (min)"))


class WhatAppendDayWrites(unittest.TestCase):
    """End to end through append_day, with the Sheet mocked out."""

    def _written(self, records):
        ws = mock.MagicMock()
        ws.get_all_values.return_value = [KL._columns()]
        sh = mock.MagicMock()
        sh.worksheet.return_value = ws
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        return_value=sh), \
                mock.patch("automations.recruiting_report.fill._retry",
                           side_effect=lambda fn, *a, **k: fn(*a, **k)):
            n = KL.append_day(dt.date(2026, 9, 16), "Akashdeep Rai", records,
                              verbose=False)
        self.assertEqual(n, len(records))
        return ws.append_rows.call_args[0][0]

    def test_a_rep_who_sold_nothing_logs_a_zero_not_a_blank(self):
        rows = self._written([{
            "ID": "1", "Rep": "A", "Total Knocks": 40, "Sale": 0,
            "Come Back": 0, "Gaps": 0, "Total Gaps (min)": 0,
        }])
        cols = KL._columns()
        cell = dict(zip(cols, rows[0]))
        self.assertEqual(cell["Sale"], "0")
        self.assertEqual(cell["Come Back"], "0")
        self.assertEqual(cell["Total Knocks"], "40")

    def test_a_rep_with_no_tracker_row_still_logs_blank_gaps(self):
        rows = self._written([{"ID": "2", "Rep": "B", "Total Knocks": 10}])
        cell = dict(zip(KL._columns(), rows[0]))
        self.assertEqual(cell["Gaps"], "")
        self.assertEqual(cell["Total Gaps (min)"], "")

    def test_the_two_cases_are_distinguishable_in_the_sheet(self):
        """Clocked in with zero gaps, vs never clocked in. Before the fix both
        wrote an empty cell and nothing downstream could tell them apart."""
        rows = self._written([
            {"ID": "1", "Rep": "Clocked in", "Gaps": 0,
             "Total Gaps (min)": 0},
            {"ID": "2", "Rep": "Never clocked in"},
        ])
        cols = KL._columns()
        a = dict(zip(cols, rows[0]))
        b = dict(zip(cols, rows[1]))
        self.assertEqual(a["Gaps"], "0")
        self.assertEqual(b["Gaps"], "")

    def test_the_date_and_office_lead_every_row(self):
        rows = self._written([{"ID": "1", "Rep": "A"}])
        self.assertEqual(rows[0][0], "2026-09-16")
        self.assertEqual(rows[0][1], "Akashdeep Rai")

    def test_no_records_writes_nothing(self):
        self.assertEqual(KL.append_day(dt.date(2026, 9, 16), "X", [],
                                       verbose=False), 0)


class ReadingStaysTolerant(unittest.TestCase):
    """Rows written before 2026-09-17 hold a blank where a 0 belongs, and
    cannot be repaired. The readers must keep treating both alike."""

    def _grid(self, knocks, talk_to):
        return [["Date", "Office", "Rep", "Total Knocks", "Total Talk to"],
                ["2026-09-16", "Kash Rai", "A", knocks, talk_to]]

    def test_a_legacy_blank_reads_as_zero(self):
        got = KL.activity_from(self._grid("", ""), "Kash Rai")
        self.assertEqual(got["a"][dt.date(2026, 9, 16)], {"TK": 0, "TT": 0})

    def test_an_explicit_zero_reads_as_zero_too(self):
        got = KL.activity_from(self._grid("0", "0"), "Kash Rai")
        self.assertEqual(got["a"][dt.date(2026, 9, 16)], {"TK": 0, "TT": 0})

    def test_real_numbers_still_read(self):
        got = KL.activity_from(self._grid("40", "7"), "Kash Rai")
        self.assertEqual(got["a"][dt.date(2026, 9, 16)], {"TK": 40, "TT": 7})


if __name__ == "__main__":
    unittest.main()
