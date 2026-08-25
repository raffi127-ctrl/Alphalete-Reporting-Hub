"""Tests for the day-behind empty-week tolerance in section_pull.

WHY: BOX publishes yesterday's sales later the same day, so on TUESDAY — the
day the board's week rolls — the pinned week is completely empty at 5am, the
Tableau Crosstab dialog comes up with NO worksheets, and the pull died with
"saw 0 thumb(s)". That fired `drop-org-sales-board / section: BOX` every
Tuesday (2026-08-18, 2026-08-25) for a section that is a day behind on purpose
and gets filled by the 14:30 catchup.

The tolerance has to stay narrow, so the cases that must still FAIL are the
point of this file: a dialog that listed other sheets (rename / view changed),
a mid-week empty week, the afternoon catchup, and any spec not flagged
day_behind.

Run:  .venv/bin/python -m pytest automations/org_sales_board/test_section_pull_empty_week.py
  or  .venv/bin/python -m unittest automations.org_sales_board.test_section_pull_empty_week
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.org_sales_board import section_pull as sp


MON = dt.date(2026, 8, 24)
TUE = dt.date(2026, 8, 25)
WED = dt.date(2026, 8, 26)
MORNING = dt.datetime(2026, 8, 25, 5, 10)
AFTERNOON = dt.datetime(2026, 8, 25, 14, 30)

EMPTY = RuntimeError(
    "Couldn't find the 'Daily Tracker Sales' sheet in the Crosstab dialog — "
    "saw 0 thumb(s): []. The view may have changed.")
RENAMED = RuntimeError(
    "Couldn't find the 'Daily Tracker Sales' sheet in the Crosstab dialog — "
    "saw 2 thumb(s): ['Daily Sales by ICD', 'Weekly Tracker']. "
    "The view may have changed.")


class EmptyDialogTest(unittest.TestCase):
    def test_zero_thumbs_is_the_empty_viz(self):
        self.assertTrue(sp.is_empty_crosstab_dialog(EMPTY))

    def test_other_sheets_listed_is_a_real_change(self):
        self.assertFalse(sp.is_empty_crosstab_dialog(RENAMED))


class EmptyWeekExpectedTest(unittest.TestCase):
    def test_tuesday_morning_box_is_a_wait(self):
        self.assertTrue(
            sp.empty_week_expected(sp.BOX_SPEC, TUE, MORNING))

    def test_tuesday_afternoon_is_a_failure(self):
        # The 14:30 catchup runs after the extract lands; an empty week there
        # is real and must still alert.
        self.assertFalse(
            sp.empty_week_expected(sp.BOX_SPEC, TUE, AFTERNOON))

    def test_midweek_empty_week_is_a_failure(self):
        # Wednesday: Monday AND Tuesday are complete, so a day-behind source
        # has to have something.
        self.assertFalse(
            sp.empty_week_expected(sp.BOX_SPEC, WED, MORNING))

    def test_monday_reports_last_week_and_must_be_full(self):
        # Monday still reports the just-finished week — all 7 days complete.
        self.assertFalse(
            sp.empty_week_expected(sp.BOX_SPEC, MON,
                                   dt.datetime(2026, 8, 24, 5, 10)))

    def test_sections_that_are_not_day_behind_never_tolerate_it(self):
        for spec in (sp.FIBER_SPEC, sp.NDS_SPEC, sp.B2B_SPEC):
            self.assertFalse(
                sp.empty_week_expected(spec, TUE, MORNING), spec.section_label)

    def test_only_box_is_flagged_day_behind(self):
        flagged = sorted(k for k, s in sp.SPECS.items() if s.day_behind)
        self.assertEqual(flagged, ["box"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
