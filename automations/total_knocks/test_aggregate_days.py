"""Folding several days of knocks into one board must not invent numbers.

Run:  PYTHONPATH=. python -m unittest \
          automations.total_knocks.test_aggregate_days

WHAT THIS GUARDS (Raf 2026-08-25, "can we have it where it asks me what day I
want or days? So it can do a range?"). A range board is a FOLD, and a fold has
exactly two ways to go wrong quietly:

  1. Single-day requests stop being single-day requests. Every /knocks ever
     sent is one day; if the range code path changes what those produce, the
     feature broke the thing it was added next to. `aggregate_days` on one day
     returns THOSE ROWS, unchanged, and the tests below pin it.

  2. 'Avg. Hrs Knocking' quietly stops meaning hours. It is derived as
     (Last Knock − First Knock) − Total Gaps — single-day clock arithmetic. Run
     that formula over a folded row, whose First/Last span a week and whose
     gaps are a week's worth, and it prints a small wrong number instead of
     raising. So the fold computes the hours PER DAY and averages them, the
     board reads that value rather than re-deriving it, and both halves of that
     contract are tested — the fold's output AND the board's refusal to
     recompute.

The counts themselves are the easy part; they're here so a refactor that
"simplifies" the merge can't drop Gaps or double-count a rep who appears on
some days and not others.

No browser, no Sheet, no PIL beyond the render import: every input below is a
hand-written dict.
"""
from __future__ import annotations

import unittest

from automations.total_knocks import render
from automations.total_knocks.aggregate import (
    COL_HRS_KNOCKING,
    aggregate_days,
    daterange,
    day_hours,
    fmt_time,
    hours_between,
    knock_time_key,
)
from automations.total_knocks.pull import (
    COL_COME_BACK,
    COL_DO_NOT_KNOCK,
    COL_FIRST_KNOCK,
    COL_GAPS,
    COL_ID,
    COL_INACCESSIBLE,
    COL_LAST_KNOCK,
    COL_NO_ANSWER,
    COL_PRES_NI,
    COL_REP,
    COL_SALE,
    COL_TALK_TO_NI,
    COL_TOTAL_GAPS,
    COL_TOTAL_KNOCKS,
    COL_TOTAL_LEADS_KNOCKED,
    COL_TOTAL_TALK_TO,
)
import datetime as dt


def house_row(rid="101", rep="Ana Diaz", knocks=100, first="9:00 AM",
              last="5:00 PM", gaps=1, total_gaps=30, **over) -> dict:
    """One rep's house-shaped disposition row, with every column the combined
    board needs so `render` can draw it without complaining."""
    rec = {
        COL_ID: rid, COL_REP: rep,
        COL_TOTAL_LEADS_KNOCKED: knocks, COL_TOTAL_KNOCKS: knocks,
        COL_TOTAL_TALK_TO: 10,
        COL_FIRST_KNOCK: first, COL_LAST_KNOCK: last,
        COL_GAPS: gaps, COL_TOTAL_GAPS: total_gaps,
        COL_NO_ANSWER: 5, COL_TALK_TO_NI: 4, COL_PRES_NI: 3,
        COL_COME_BACK: 2, COL_SALE: 1, COL_INACCESSIBLE: 1,
        COL_DO_NOT_KNOCK: 0,
    }
    rec.update(over)
    return rec


class SingleDayIsUntouched(unittest.TestCase):
    """The whole promise of the range feature: one day still behaves exactly
    as it did before the feature existed."""

    def test_one_day_returns_the_same_rows(self):
        rows = [house_row(), house_row(rid="102", rep="Bo Ito")]
        out = aggregate_days([rows])
        self.assertEqual(out, rows)

    def test_one_day_adds_no_precomputed_hours_column(self):
        # If the fold added Avg. Hrs Knocking here, the board would read the
        # fold's value instead of deriving it, and a one-day board would take
        # a different code path than it has all along.
        out = aggregate_days([[house_row()]])
        self.assertNotIn(COL_HRS_KNOCKING, out[0])

    def test_empty_days_are_dropped_not_counted(self):
        rows = [house_row()]
        self.assertEqual(aggregate_days([[], rows, []]), rows)
        self.assertEqual(aggregate_days([[], []]), [])
        self.assertEqual(aggregate_days([]), [])


class CountsAddUp(unittest.TestCase):

    def test_counts_sum_across_days(self):
        out = aggregate_days([
            [house_row(knocks=100, gaps=1, total_gaps=30)],
            [house_row(knocks=60, gaps=2, total_gaps=45)],
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][COL_TOTAL_KNOCKS], 160)
        self.assertEqual(out[0][COL_GAPS], 3)
        self.assertEqual(out[0][COL_TOTAL_GAPS], 75)
        self.assertEqual(out[0][COL_SALE], 2)

    def test_rep_missing_from_a_day_is_not_double_counted(self):
        # Ana knocked both days, Bo only the second. Bo's totals are Bo's.
        out = aggregate_days([
            [house_row(rid="101", rep="Ana Diaz", knocks=100)],
            [house_row(rid="101", rep="Ana Diaz", knocks=50),
             house_row(rid="102", rep="Bo Ito", knocks=70)],
        ])
        by_rep = {r[COL_REP]: r for r in out}
        self.assertEqual(by_rep["Ana Diaz"][COL_TOTAL_KNOCKS], 150)
        self.assertEqual(by_rep["Bo Ito"][COL_TOTAL_KNOCKS], 70)

    def test_reps_are_matched_by_badge_id_not_by_name(self):
        # The same rep, spelled two ways across two days, is ONE row.
        out = aggregate_days([
            [house_row(rid="101", rep="Ana Diaz", knocks=100)],
            [house_row(rid="101", rep="ana diaz", knocks=50)],
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][COL_TOTAL_KNOCKS], 150)


class KnockTimesAreAveraged(unittest.TestCase):
    """A folded board shows the rep's AVERAGE start and finish, not the
    earliest and latest in the span (Megan 2026-09-01).

    Over a week, min/max answers "what is the earliest this rep EVER started" —
    one keen Tuesday sets it and no amount of late starts moves it, which is
    the opposite of a true idea of the rep. The weekly board has averaged since
    2026-08-22 and the two land in front of the same reader.
    """

    def test_first_and_last_are_averages(self):
        out = aggregate_days([
            [house_row(first="9:00 AM", last="5:00 PM")],
            [house_row(first="8:15 AM", last="4:00 PM")],
            [house_row(first="10:00 AM", last="7:45 PM")],
        ])
        # 9:00 + 8:15 + 10:00 -> 9:05 ; 5:00 + 4:00 + 7:45 -> 5:35
        self.assertEqual(out[0][COL_FIRST_KNOCK], "9:05 AM")
        self.assertEqual(out[0][COL_LAST_KNOCK], "5:35 PM")

    def test_a_single_day_is_left_exactly_as_scraped(self):
        """A ONE-day board must show the day's real times, not an "average"
        of anything (Megan 2026-09-01: "this shouldn't change the daily 1st
        and last knock though because that's only one day").

        It holds because the mean of one value is that value — but it is the
        property people will rely on, so it is pinned rather than reasoned
        about. The daily boards do not fold at all: aggregate_days has exactly
        one caller, the /knocks request path.
        """
        out = aggregate_days([[house_row(first="1:25 PM", last="10:42 PM")]])
        self.assertEqual(out[0][COL_FIRST_KNOCK], "1:25 PM")
        self.assertEqual(out[0][COL_LAST_KNOCK], "10:42 PM")

    def test_only_days_the_rep_knocked_count(self):
        """A blank day must not drag the average toward an hour nobody
        worked — the divisor is days KNOCKED, not days in the span."""
        out = aggregate_days([
            [house_row(first="9:00 AM", last="5:00 PM")],
            [house_row(first="", last="")],
            [house_row(first="10:00 AM", last="6:00 PM")],
        ])
        self.assertEqual(out[0][COL_FIRST_KNOCK], "9:30 AM")
        self.assertEqual(out[0][COL_LAST_KNOCK], "5:30 PM")

    def test_a_folded_time_reparses_to_what_went_in(self):
        # fmt_time is the inverse of knock_time_key, or the board's own sort
        # would push folded rows to the bottom as unparsable.
        for s in ("8:15 AM", "12:00 PM", "12:30 AM", "7:45 PM"):
            self.assertEqual(fmt_time(knock_time_key(s)), s)

    def test_a_day_with_no_usable_time_leaves_the_cell_blank(self):
        out = aggregate_days([
            [house_row(first="", last="")],
            [house_row(first="", last="")],
        ])
        self.assertEqual(out[0][COL_FIRST_KNOCK], "")
        self.assertEqual(out[0][COL_LAST_KNOCK], "")


class HoursAreAveragedPerKnockingDay(unittest.TestCase):
    """The column Raf reads as "AVG Hrs knocking per day"."""

    def test_hours_are_the_mean_of_the_days_worked(self):
        # Day 1: 9:00–5:00 = 480 − 30 gaps = 450. Day 2: 9:00–3:00 = 360 − 0 = 360.
        out = aggregate_days([
            [house_row(first="9:00 AM", last="5:00 PM", total_gaps=30)],
            [house_row(first="9:00 AM", last="3:00 PM", total_gaps=0)],
        ])
        self.assertEqual(out[0][COL_HRS_KNOCKING], str(round((450 + 360) / 2)))

    def test_days_the_rep_did_not_knock_do_not_drag_the_average_down(self):
        # Three days in the span, one with no usable times: the average is
        # over the TWO days he actually knocked, not over three.
        out = aggregate_days([
            [house_row(first="9:00 AM", last="5:00 PM", total_gaps=0)],
            [house_row(first="", last="", total_gaps=0)],
            [house_row(first="9:00 AM", last="5:00 PM", total_gaps=0)],
        ])
        self.assertEqual(out[0][COL_HRS_KNOCKING], "480")

    def test_a_rep_who_never_had_usable_times_gets_a_blank(self):
        out = aggregate_days([
            [house_row(first="", last="")],
            [house_row(first="", last="")],
        ])
        self.assertEqual(out[0][COL_HRS_KNOCKING], "")

    def test_the_naive_formula_would_have_been_wrong(self):
        """The bug this whole design exists to avoid, stated as a test.

        Re-deriving hours from the FOLDED row — (latest − earliest) − summed
        gaps — is what a server-side date range would have handed the board.
        Pin the two numbers apart so nobody 'simplifies' the fold back into it.
        """
        days = [
            [house_row(first="9:00 AM", last="5:00 PM", total_gaps=60)],
            [house_row(first="9:00 AM", last="5:00 PM", total_gaps=60)],
        ]
        out = aggregate_days(days)
        naive = hours_between(out[0][COL_FIRST_KNOCK], out[0][COL_LAST_KNOCK],
                              out[0][COL_TOTAL_GAPS])
        self.assertEqual(naive, 360)                 # 480 − 120 — wrong
        self.assertEqual(out[0][COL_HRS_KNOCKING], "420")   # 480 − 60, right


class TheBoardReadsTheFoldedHours(unittest.TestCase):
    """The other half of the contract: `render` must not recompute."""

    def test_combined_sub_uses_the_precomputed_column(self):
        folded = aggregate_days([
            [house_row(first="9:00 AM", last="5:00 PM", total_gaps=60)],
            [house_row(first="9:00 AM", last="5:00 PM", total_gaps=60)],
        ])
        header, rows = render._table_from_rows(folded)
        self.assertIn(COL_HRS_KNOCKING, header)
        sub = render._combined_sub(header, rows)
        hrs_at = render.COMBINED_KNOCKS_HEADERS.index(COL_HRS_KNOCKING)
        self.assertEqual(sub[0][hrs_at], "420")

    def test_single_day_still_derives_it(self):
        header, rows = render._table_from_rows([
            house_row(first="9:00 AM", last="5:00 PM", total_gaps=60)])
        self.assertNotIn(COL_HRS_KNOCKING, header)
        sub = render._combined_sub(header, rows)
        hrs_at = render.COMBINED_KNOCKS_HEADERS.index(COL_HRS_KNOCKING)
        self.assertEqual(sub[0][hrs_at], "420")      # 480 − 60

    def test_the_derived_cell_follows_its_own_rep_through_the_sort(self):
        """The board sorts alphabetically AFTER building rows. A derived cell
        computed against the unsorted order would land on the wrong rep — the
        kind of wrong that looks perfectly plausible on the image."""
        header, rows = render._table_from_rows([
            house_row(rid="1", rep="Zoe Vance", first="9:00 AM",
                      last="5:00 PM", total_gaps=0),      # 480
            house_row(rid="2", rep="Ana Diaz", first="9:00 AM",
                      last="11:00 AM", total_gaps=0),     # 120
        ])
        sub = render._combined_sub(header, rows)
        hrs_at = render.COMBINED_KNOCKS_HEADERS.index(COL_HRS_KNOCKING)
        rep_at = render.COMBINED_KNOCKS_HEADERS.index(COL_REP)
        got = {r[rep_at]: r[hrs_at] for r in sub}
        self.assertEqual(got, {"Ana Diaz": "120", "Zoe Vance": "480"})


class GapsOnlyOfficesFoldToo(unittest.TestCase):
    """NDS offices have no Disposition page — the Time Tracker IS the board, so
    a range has to fold those rows as well (Megan 2026-08-25)."""

    def _tt_row(self, first, last, gaps, total_gaps, breaks="", sales=""):
        return {COL_ID: "77", COL_REP: "Ivy Nakamura",
                COL_FIRST_KNOCK: first, COL_LAST_KNOCK: last,
                COL_GAPS: gaps, COL_TOTAL_GAPS: total_gaps,
                "Breaks": breaks, "Sales Time": "", "Sales": sales}

    def test_gaps_only_rows_keep_their_shape_after_folding(self):
        out = aggregate_days([
            [self._tt_row("9:00 AM", "4:00 PM", 1, 20)],
            [self._tt_row("8:30 AM", "5:30 PM", 2, 25)],
        ])
        self.assertEqual(len(out), 1)
        # No Total Knocks key anywhere: still a gaps-only board, not a
        # wireless one that would render the wrong columns.
        self.assertNotIn(COL_TOTAL_KNOCKS, out[0])
        self.assertEqual(render.knocks_shape(out), render.SHAPE_GAPS_ONLY)
        self.assertEqual(out[0][COL_TOTAL_GAPS], 45)
        # Averaged like every other folded board: 9:00+8:30 -> 8:45,
        # 4:00+5:30 -> 4:45. Gaps-only offices are described by their knock
        # TIMES above all, so an average matters more here, not less.
        self.assertEqual(out[0][COL_FIRST_KNOCK], "8:45 AM")
        self.assertEqual(out[0][COL_LAST_KNOCK], "4:45 PM")

    def test_blank_when_zero_columns_stay_blank(self):
        # The live p=510 table leaves zeros empty; a fold of nothing but zeros
        # must not start printing '0' where the page shows blank.
        out = aggregate_days([
            [self._tt_row("9:00 AM", "4:00 PM", 0, 0)],
            [self._tt_row("9:00 AM", "4:00 PM", 0, 0)],
        ])
        self.assertEqual(out[0]["Sales"], "")
        self.assertEqual(out[0]["Breaks"], "")

    def test_blank_when_zero_columns_sum_when_they_have_values(self):
        out = aggregate_days([
            [self._tt_row("9:00 AM", "4:00 PM", 0, 0, sales="2")],
            [self._tt_row("9:00 AM", "4:00 PM", 0, 0, sales="3")],
        ])
        self.assertEqual(out[0]["Sales"], 5)


class SpanHelpers(unittest.TestCase):

    def test_daterange_is_inclusive_both_ends(self):
        days = daterange(dt.date(2026, 8, 18), dt.date(2026, 8, 23))
        self.assertEqual(len(days), 6)
        self.assertEqual(days[0], dt.date(2026, 8, 18))
        self.assertEqual(days[-1], dt.date(2026, 8, 23))

    def test_a_backwards_range_is_empty_never_swapped(self):
        self.assertEqual(daterange(dt.date(2026, 8, 23), dt.date(2026, 8, 18)),
                         [])

    def test_day_hours_blank_when_the_day_has_no_span(self):
        self.assertIsNone(day_hours(house_row(first="5:00 PM", last="9:00 AM")))
        self.assertIsNone(day_hours(house_row(first="", last="5:00 PM")))

    def test_gaps_never_push_hours_below_zero(self):
        self.assertEqual(hours_between("9:00 AM", "10:00 AM", 999), 0)


class TitleAndFilenameSpan(unittest.TestCase):
    """A one-day board's title names the WEEKDAY (Eve 2026-08-28); the
    filename must not change at all."""

    def test_single_day_title_leads_with_the_weekday(self):
        d = dt.date(2026, 8, 23)
        self.assertEqual(render._title_span(d), "Sunday, August 23, 2026")
        self.assertEqual(render._title_span(d, d), "Sunday, August 23, 2026")
        self.assertEqual(render._file_span(d), "2026-08-23")
        self.assertEqual(render._file_span(d, d), "2026-08-23")

    def test_range_titles_read_naturally(self):
        self.assertEqual(
            render._title_span(dt.date(2026, 8, 18), dt.date(2026, 8, 23)),
            "August 18–23, 2026")
        self.assertEqual(
            render._title_span(dt.date(2026, 8, 30), dt.date(2026, 9, 2)),
            "August 30 – September 2, 2026")
        self.assertEqual(
            render._title_span(dt.date(2026, 12, 30), dt.date(2027, 1, 2)),
            "December 30, 2026 – January 2, 2027")

    def test_range_filenames_carry_both_dates(self):
        self.assertEqual(
            render._file_span(dt.date(2026, 8, 18), dt.date(2026, 8, 23)),
            "2026-08-18_2026-08-23")


if __name__ == "__main__":
    unittest.main()
