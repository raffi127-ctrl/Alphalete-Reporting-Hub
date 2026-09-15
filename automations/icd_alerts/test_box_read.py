"""Counting Box contracts into the shape every other surface already reads.

tally() is arithmetic over rows and is tested here. read_day() drives a
browser and is not -- there is no Box account on this machine to sign into.
So everything that can be wrong about the COUNTING is covered, and what
stays unproven is the navigation, which the first real run will show.

The rows below are shaped like Ryan McSpadden's own Contracts grid.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.icd_alerts import box_read as B

DAY = dt.date(2026, 9, 15)


def _row(agent, status, when="09/15/2026 06:13 PM", volume="51,000"):
    return {"Agent": agent, "Contract Substatus": status,
            "Initiated Date": when, "Adjusted Annual Volume": volume,
            "Business Name": "Somewhere LLC"}


class ASaleIsCountedOncePerContract(unittest.TestCase):

    def test_the_six_sold_statuses_all_count(self):
        rows = [_row("Max Allen", s) for s in
                ("TPV Passed", "Ready for booking", "In Progress",
                 "Missing Documents", "Submitted to supplier",
                 "Accepted by Supplier")]
        out = B.tally(rows, DAY)
        self.assertEqual(out["sales"]["Max Allen"]["Sales"], 6)

    def test_volume_adds_up_across_a_reps_day(self):
        rows = [_row("Max Allen", "TPV Passed", volume="51,000"),
                _row("Max Allen", "TPV Passed", volume="18,248")]
        out = B.tally(rows, DAY)
        self.assertEqual(out["sales"]["Max Allen"]["Sales"], 2)
        self.assertEqual(out["sales"]["Max Allen"]["Volume"], 69248)

    def test_a_status_that_is_not_a_sale_is_not_counted(self):
        rows = [_row("Max Allen", s) for s in
                ("PDF Generated", "TPV Sent", "Cancelled by Supplier")]
        self.assertEqual(B.tally(rows, DAY)["sales"], {})


class AwaitingSignatureIsCountedSeparately(unittest.TestCase):
    """It is the step BEFORE a sale. Folding it in would inflate a number
    people are paid on with work that has not closed."""

    def test_it_lands_in_records_not_sales(self):
        out = B.tally([_row("Sohaib Hafeez", "Awaiting Signature")], DAY)
        self.assertEqual(out["records"], {"Sohaib Hafeez": 1})
        self.assertEqual(out["sales"], {})

    def test_a_rep_can_have_both_in_one_day(self):
        rows = [_row("Sohaib Hafeez", "Awaiting Signature"),
                _row("Sohaib Hafeez", "Awaiting Signature"),
                _row("Sohaib Hafeez", "TPV Passed", volume="10,099")]
        out = B.tally(rows, DAY)
        self.assertEqual(out["records"]["Sohaib Hafeez"], 2)
        self.assertEqual(out["sales"]["Sohaib Hafeez"],
                         {"Sales": 1, "Volume": 10099})


class OnlyTodaysRows(unittest.TestCase):
    """The grid is sorted newest first and a day's contracts sit among
    yesterday's. A reader that takes what it is given folds the whole week
    into this morning."""

    def test_yesterday_is_ignored(self):
        rows = [_row("Max Allen", "TPV Passed", when="09/15/2026 06:13 PM"),
                _row("Max Allen", "TPV Passed", when="09/14/2026 06:43 PM")]
        self.assertEqual(B.tally(rows, DAY)["sales"]["Max Allen"]["Sales"], 1)

    def test_start_date_style_future_rows_do_not_leak_in(self):
        # "APR 2027" has no day; an unreadable cell must not count as today.
        rows = [_row("Max Allen", "TPV Passed", when="APR 2027")]
        self.assertEqual(B.tally(rows, DAY)["sales"], {})

    def test_an_unreadable_date_is_unknown_not_today(self):
        self.assertIsNone(B.initiated_on(""))
        self.assertIsNone(B.initiated_on("APR 2027"))
        self.assertIsNone(B.initiated_on("13/45/2026"))
        self.assertEqual(B.initiated_on("09/15/2026 06:13 PM"), DAY)


class BadRowsDoNotBecomeBadNumbers(unittest.TestCase):

    def test_a_row_with_no_rep_is_skipped_not_bucketed(self):
        # Inventing a rep out of a blank puts sales on a board under a blank
        # heading.
        out = B.tally([_row("", "TPV Passed"), _row("  ", "TPV Passed")], DAY)
        self.assertEqual(out["sales"], {})

    def test_an_unreadable_volume_is_zero_not_a_guess(self):
        out = B.tally([_row("Max Allen", "TPV Passed", volume="—")], DAY)
        self.assertEqual(out["sales"]["Max Allen"],
                         {"Sales": 1, "Volume": 0})

    def test_a_status_nobody_ruled_on_is_reported(self):
        out = B.tally([_row("Max Allen", "Awaiting QC")], DAY)
        self.assertEqual(out["unknown"], ["Awaiting QC"])
        self.assertEqual(out["sales"], {})

    def test_no_rows_is_an_empty_day_not_a_crash(self):
        out = B.tally([], DAY)
        self.assertEqual(out, {"records": {}, "sales": {}, "unknown": []})


class TheShapeMatchesWhatEverythingElseReads(unittest.TestCase):
    """icd_sales_board/relay_read.py: "the shape on the wire IS the shape of
    the board". If this drifts from sara_read's shape, the board and the
    alerts both stop working for Box with nothing to say why."""

    def test_it_returns_records_and_sales_like_saraplus_does(self):
        out = B.tally([_row("Max Allen", "TPV Passed")], DAY)
        self.assertIn("records", out)
        self.assertIn("sales", out)
        self.assertIsInstance(out["sales"]["Max Allen"], dict)

    def test_the_sales_keys_are_the_board_columns(self):
        from automations.shared import servicecloud as SC
        out = B.tally([_row("Max Allen", "TPV Passed")], DAY)
        self.assertEqual(sorted(out["sales"]["Max Allen"]),
                         sorted(SC.BOX_METRICS))


if __name__ == "__main__":
    unittest.main()
