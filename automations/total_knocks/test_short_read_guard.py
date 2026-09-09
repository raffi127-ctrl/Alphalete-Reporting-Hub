"""A Disposition grid read SHORT of the people who clocked in must never mail.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.total_knocks.test_short_read_guard

WHAT THIS GUARDS (Eve 2026-09-08). Christian Esposito's daily knock board went
out on 2026-09-07 with **2 reps**; ownerville had **22** for that office and
day, and the same scrape re-run by hand returned all 22. The Friday before it
mailed 8 of 27. Two of the names on the 9/7 board are not in his office at all.

The mechanism: `_scrape_rows` started walking the grid as soon as ONE tbody row
existed, and the captainship capture reuses ONE page for ~44 owners — so the
walk could read a grid that was still filling, or one still holding the
previous office's rows. Nothing raised, nothing looked wrong: a short board and
a quiet day render identically.

The Time Tracker is the number that knows better — a JSON fetch of everyone who
clocked in, so it does not share the grid's failure mode. The guard is two
steps, and BOTH halves matter:

  Disposition < Time Tracker            →  read the grid again, keep the larger
  still short after the re-read         →  KnocksPullFailed (grey note, send held)

A rep can legitimately clock in and disposition nothing, so the refusal needs
both an ABSOLUTE gap (a five-rep office is not judged on percentages) and a
RATIO (a forty-rep office missing five is a normal day). These tests pin the
thresholds against the two real days, and pin the days that must NOT fire —
because a guard that cried wolf would hold captains' mail every morning, which
is the failure this repo already knows the shape of.

Pure functions only: no browser, no page, no network.
"""
from __future__ import annotations

import unittest

from automations.total_knocks import pull


class ShortReadIsWorthReReading(unittest.TestCase):
    def test_the_two_real_days_ask_for_a_re_read(self):
        # Christian Esposito, 2026-09-07 and 2026-09-04.
        self.assertTrue(pull.disposition_read_is_short(2, 22))
        self.assertTrue(pull.disposition_read_is_short(8, 27))

    def test_one_missing_rep_still_asks(self):
        # The re-read is one navigation; it is the cheap half of the guard, so
        # any shortfall qualifies. The expensive judgement is short_read_error.
        self.assertTrue(pull.disposition_read_is_short(26, 27))

    def test_a_full_read_does_not(self):
        # What every healthy office logged on 2026-09-08: 22/22, 13/13, 12/12.
        self.assertFalse(pull.disposition_read_is_short(22, 22))

    def test_more_dispositions_than_clock_ins_does_not(self):
        # Possible when a rep dispositions without a Time Tracker row. Not a
        # short read, and not this guard's business.
        self.assertFalse(pull.disposition_read_is_short(24, 22))

    def test_an_empty_grid_does_not(self):
        # rows == [] is the NDS/gaps-only office (Isaiah): the caller already
        # falls back to Time Tracker rows, and firing here would turn that
        # supported shape into a failure.
        self.assertFalse(pull.disposition_read_is_short(0, 22))

    def test_no_time_tracker_does_not(self):
        # The TT fetch is non-fatal while we have disposition rows, so it can
        # be {}. With no second opinion there is nothing to compare against —
        # the guard must go quiet, not guess.
        self.assertFalse(pull.disposition_read_is_short(22, 0))


class ShortReadRefusesToPublish(unittest.TestCase):
    def test_the_two_real_days_refuse(self):
        for rows, tt in ((2, 22), (8, 27)):
            with self.subTest(rows=rows, tt=tt):
                why = pull.short_read_error(rows, tt)
                self.assertIsNotNone(why)
                self.assertIn(str(rows), why)
                self.assertIn(str(tt), why)

    def test_a_full_read_does_not_refuse(self):
        self.assertIsNone(pull.short_read_error(22, 22))

    def test_a_few_walk_ons_do_not_refuse(self):
        # 27 clocked in, 25 knocked doors: two reps logged in and left. This is
        # a normal day and must mail.
        self.assertIsNone(pull.short_read_error(25, 27))

    def test_a_small_office_is_not_judged_on_ratio(self):
        # 3 of 5 is 60%, but the absolute gap is 2 — on an office this size
        # that is one rep who clocked in and one who went home.
        self.assertIsNone(pull.short_read_error(3, 5))

    def test_a_big_office_missing_a_handful_does_not_refuse(self):
        # Raf's office: 41 clocked in, 36 dispositioned. Five walk-ons is not a
        # broken grid, and holding his mail every morning is worse than the
        # five rows.
        self.assertIsNone(pull.short_read_error(36, 41))

    def test_half_an_office_missing_refuses(self):
        self.assertIsNotNone(pull.short_read_error(20, 41))

    def test_empty_sides_never_refuse(self):
        # Same two exemptions as the re-read test, restated here because this
        # is the half that can HOLD a captain's mail.
        self.assertIsNone(pull.short_read_error(0, 22))
        self.assertIsNone(pull.short_read_error(22, 0))


class BothPathsRunTheGuard(unittest.TestCase):
    """The captainship capture and Raf's own board are two copies of the same
    scrape sequence (rashad_metrics.knocks_pull._scrape_day_on_page and
    total_knocks.pull.pull_disposition_day). A fix in one of them leaves the
    other publishing short boards, which is exactly how this family of bugs
    survives a refactor — so pin that both call it."""

    def test_the_walk_waits_for_the_grid_to_settle(self):
        # The first half of the fix, and the one no threshold can stand in for:
        # a wait satisfied by ONE row is what let a half-filled grid be read at
        # all. Both paths reach the grid through this one function.
        import inspect
        self.assertIn("_wait_rows_settled",
                      inspect.getsource(pull._scrape_rows))

    def test_source_of_both_paths_calls_the_guard(self):
        import inspect
        from automations.rashad_metrics import knocks_pull
        for fn in (knocks_pull._scrape_day_on_page,
                   pull.pull_disposition_day):
            src = inspect.getsource(fn)
            with self.subTest(fn=fn.__name__):
                self.assertIn("disposition_read_is_short", src)
                self.assertIn("short_read_error", src)


if __name__ == "__main__":
    unittest.main()
