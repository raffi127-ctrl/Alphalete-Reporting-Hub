"""The blocks of the morning photo are found BY HEADER, at any width.

Two things used to be spelled out in numbers and broke when the Talk-To columns
landed:

  * the DAY block -- `_day_block` counted six columns across for Cx and seven for
    Roll Call. The trio made the block eleven wide, so six across became
    'Total Talk-To's' and the roll-call probe landed on '% of TT's per knock':
    the post silently lost Cx and the roll call.
  * the RUNNING WEEK block -- the 'ranking' section showed A..J. The five weekly
    Talk-To columns pushed the block to D..O, so J cut it off mid-block.

Rafael asked for the new columns IN the screenshots (2026-09-11), daily and
weekly. That makes a third thing matter: the totals row is rewritten as a SUM,
and four of the new columns are rates. Summing them is nonsense, so they are
shown and left alone.
"""
import datetime as dt
import unittest

from automations.alphalete_production import capture


DAY_OLD = ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx", "Roll Call"]
DAY_NEW = ["Apps", "Int", "Int Up", "DTV", "NL", "TK",
           "Total Talk-To's", "% of TT's per knock", "AVG app per TT",
           "Cx", "Roll Call"]
WK_OLD = ["APPS", "INT", "INT UP", "DTV", "NL", "TK", "Cx"]
WK_NEW = ["APPS", "INT", "INT UP", "DTV", "NL", "TK",
          "AVG Total Knocks per day", "Total Talk-To's", "AVG TT's per day",
          "% of TT's per knock", "AVG TTs per app", "Cx"]
DAYS = ["MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"]
WEEK = [dt.date(2026, 9, 7) + dt.timedelta(days=i) for i in range(7)]


def grid(block, weekly=WK_OLD):
    """Row 1 banners, row 2 day-of-month, row 3 sub-headers."""
    r1 = ["", "", "", "RUNNING WEEK TOTALS"] + [""] * (len(weekly) - 1)
    r2 = ["", "", ""] + [""] * len(weekly)
    r3 = ["#", "", "Rep"] + list(weekly)
    r1 += ["LAST WEEK'S TOTALS"]; r2 += [""]; r3 += ["APPS"]
    for day, date in zip(DAYS, WEEK):
        r1 += [day] + [""] * (len(block) - 1)
        r2 += [str(date.day)] + [""] * (len(block) - 1)
        r3 += list(block)
    r1 += ["Trainer"]; r2 += [""]; r3 += [""]
    return [r1, r2, r3]


class DayBlockByHeader(unittest.TestCase):
    def test_old_layout_unchanged(self):
        g = grid(DAY_OLD)
        dc = capture._day_block(g, WEEK[2])
        self.assertEqual([g[2][c] for c in dc.metrics],
                         ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx"])
        self.assertEqual(g[2][dc.roll_call], "Roll Call")

    def test_cx_and_roll_call_survive_the_wider_block(self):
        """The actual regression: both used to fall off the right edge."""
        g = grid(DAY_NEW)
        dc = capture._day_block(g, WEEK[2])
        self.assertIn("Cx", [g[2][c] for c in dc.metrics])
        self.assertEqual(g[2][dc.roll_call], "Roll Call")

    def test_trio_is_photographed(self):
        """Rafael, 2026-09-11: the new columns go in the screenshots."""
        g = grid(DAY_NEW)
        shot = [g[2][c] for c in capture._day_block(g, WEEK[2]).metrics]
        for h in ("Total Talk-To's", "% of TT's per knock", "AVG app per TT"):
            self.assertIn(h, shot)

    def test_unknown_header_is_still_not_photographed(self):
        g = grid(DAY_NEW[:6] + ["Something Maud Added"] + DAY_NEW[6:])
        shot = [g[2][c] for c in capture._day_block(g, WEEK[2]).metrics]
        self.assertNotIn("Something Maud Added", shot)

    def test_sunday_is_not_truncated(self):
        g = grid(DAY_NEW)
        dc = capture._day_block(g, WEEK[6])
        self.assertIn("Cx", [g[2][c] for c in dc.metrics])
        self.assertEqual(g[2][dc.roll_call], "Roll Call")

    def test_apps_is_the_filter_and_sort_anchor(self):
        for block in (DAY_OLD, DAY_NEW):
            g = grid(block)
            dc = capture._day_block(g, WEEK[3])
            self.assertEqual(g[2][dc.apps], "Apps")
            self.assertEqual(dc.metrics[0], dc.apps)

    def test_energy_era_tab_still_reads(self):
        g = grid(["Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx", "Roll Call"])
        dc = capture._day_block(g, WEEK[1])
        self.assertEqual([g[2][c] for c in dc.metrics],
                         ["Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx"])

    def test_unknown_day_is_named_in_the_error(self):
        with self.assertRaises(RuntimeError):
            capture._day_block(grid(DAY_NEW), dt.date(2026, 9, 20))


class RunningBlockByHeader(unittest.TestCase):
    def test_old_width(self):
        g = grid(DAY_OLD, WK_OLD)
        self.assertEqual([g[2][c] for c in capture._running_block(g)], WK_OLD)

    def test_five_weekly_columns_are_included(self):
        """'ranking' showed A..J; the block is D..O now."""
        g = grid(DAY_NEW, WK_NEW)
        self.assertEqual([g[2][c] for c in capture._running_block(g)], WK_NEW)

    def test_falls_back_to_running_apps_without_banners(self):
        self.assertEqual(capture._running_block([["", "", ""], [], []]), [3])


class RatesAreNotSummed(unittest.TestCase):
    def test_rate_columns_are_left_out_of_the_subtotal(self):
        g = grid(DAY_NEW, WK_NEW)
        kept = [g[2][c] for c in capture._summable(g, capture._running_block(g))]
        self.assertIn("Total Talk-To's", kept)          # a count -- sum it
        for h in ("AVG Total Knocks per day", "AVG TT's per day",
                  "% of TT's per knock", "AVG TTs per app"):
            self.assertNotIn(h, kept)                   # a rate -- never sum it

    def test_day_rates_are_left_out_too(self):
        g = grid(DAY_NEW, WK_NEW)
        dc = capture._day_block(g, WEEK[2])
        kept = [g[2][c] for c in capture._summable(g, dc.metrics)]
        self.assertIn("Total Talk-To's", kept)
        self.assertNotIn("% of TT's per knock", kept)
        self.assertNotIn("AVG app per TT", kept)

    def test_the_old_metrics_are_all_still_summed(self):
        g = grid(DAY_NEW, WK_NEW)
        dc = capture._day_block(g, WEEK[2])
        kept = [g[2][c] for c in capture._summable(g, dc.metrics)]
        for h in ("Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx"):
            self.assertIn(h, kept)


if __name__ == "__main__":
    unittest.main()


class DayColsIsIndexSafe(unittest.TestCase):
    """`_day_block` used to return a plain `(start, end)` tuple and `zeros_streak`
    reads it as `[0]`. Turning it into a NamedTuple kept `[0]` meaning the Apps
    column ONLY because `apps` is declared first — a field reorder would silently
    point the Zero Streak screenshots at the wrong column. Pinned here, and the
    caller now says `.apps` out loud."""

    def test_index_zero_is_the_apps_column(self):
        g = grid(DAY_NEW)
        dc = capture._day_block(g, WEEK[2])
        self.assertEqual(dc[0], dc.apps)
        self.assertEqual(g[2][dc[0]], "Apps")

    def test_zeros_streak_asks_for_apps_by_name(self):
        import inspect
        from automations.alphalete_production import zeros_streak
        src = inspect.getsource(zeros_streak)
        self.assertNotIn("_day_block(grid, d)[0]", src)
        self.assertIn("_day_block(grid, d).apps", src)


class FilterRangeCoversWhatItSorts(unittest.TestCase):
    """2026-09-12: `daily_production_el` dropped out of the post twice with
    `APIError: [500]: Internal error encountered.` — the setBasicFilter range
    ended at a hardcoded column 104 while the board had grown to 221 columns and
    the section sorted on Team at 122. Sheets reports an out-of-range sort as a
    500, so it read as a transient and the noon retry produced the same error.
    """

    def test_range_covers_an_out_of_range_sort_column(self):
        end = capture._filter_end(104, [{"columnIndex": 2}], [(122, "ASCENDING")])
        self.assertGreater(end, 122, "a sort column outside the range 500s")

    def test_range_covers_an_out_of_range_filter_column(self):
        end = capture._filter_end(104, [{"columnIndex": 120}], [(3, "DESCENDING")])
        self.assertGreater(end, 120)

    def test_the_real_board_geometry_that_broke_it(self):
        """The exact payload captured off the WE 9.13 tab."""
        end = capture._filter_end(
            221,
            [{"columnIndex": 2}, {"columnIndex": 106}, {"columnIndex": 120}],
            [(122, "ASCENDING"), (3, "DESCENDING")])
        self.assertEqual(end, 221)

    def test_it_never_narrows_below_the_board_width(self):
        """Every column the photo hides has to stay inside the filter, or the
        board sorts rows the picture doesn't show."""
        end = capture._filter_end(221, [{"columnIndex": 2}], [(3, "DESCENDING")])
        self.assertEqual(end, 221)

    def test_no_literal_column_bound_is_left_in_the_filter(self):
        """The bug was a number typed once in July and never revisited. Keep it
        gone — CLAUDE.md: no hardcoded rows or columns."""
        import inspect
        src = inspect.getsource(capture._render)
        self.assertNotIn('"endColumnIndex": 104', src)
