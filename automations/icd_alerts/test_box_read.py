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


class AContractBecomesASaleAfterTheDayItWasSold(unittest.TestCase):
    """Megan 2026-09-15: "you need to track past days in case status changes
    here and we need to count something as a sale".

    A rep sells on Monday, the contract sits at "Awaiting Signature", and on
    Wednesday it passes TPV. It was always MONDAY's sale. Reading only today
    would count it on Wednesday under whoever happened to be having a good
    day, or lose it entirely.
    """

    MON = dt.date(2026, 9, 14)
    TUE = dt.date(2026, 9, 15)

    def test_a_sale_belongs_to_the_day_it_was_initiated(self):
        # Initiated Monday, and NOW reads as sold.
        rows = [_row("Max Allen", "TPV Passed", when="09/14/2026 04:43 PM")]
        out = B.tally_window(rows, [self.MON, self.TUE])
        self.assertEqual(out[self.MON]["sales"]["Max Allen"]["Sales"], 1)
        self.assertEqual(out[self.TUE]["sales"], {},
                         "a Monday sale landed on Tuesday's board")

    def test_rereading_moves_it_from_presale_to_sold_on_its_own_day(self):
        mon_row = _row("Max Allen", "Awaiting Signature",
                       when="09/14/2026 04:43 PM")
        first = B.tally_window([mon_row], [self.MON, self.TUE])
        self.assertEqual(first[self.MON]["records"]["Max Allen"], 1)
        self.assertEqual(first[self.MON]["sales"], {})

        # Wednesday's read: same contract, status has moved on.
        mon_row["Contract Substatus"] = "TPV Passed"
        second = B.tally_window([mon_row], [self.MON, self.TUE])
        self.assertEqual(second[self.MON]["sales"]["Max Allen"]["Sales"], 1)
        self.assertEqual(second[self.MON]["records"], {},
                         "it is still counted as awaiting signature as well")

    def test_each_day_is_its_own_bucket(self):
        rows = [_row("Max Allen", "TPV Passed", when="09/14/2026 01:00 PM"),
                _row("Max Allen", "TPV Passed", when="09/15/2026 01:00 PM"),
                _row("Max Allen", "TPV Passed", when="09/15/2026 02:00 PM")]
        out = B.tally_window(rows, [self.MON, self.TUE])
        self.assertEqual(out[self.MON]["sales"]["Max Allen"]["Sales"], 1)
        self.assertEqual(out[self.TUE]["sales"]["Max Allen"]["Sales"], 2)

    def test_a_day_outside_the_window_is_ignored(self):
        rows = [_row("Max Allen", "TPV Passed", when="09/01/2026 01:00 PM")]
        out = B.tally_window(rows, [self.MON, self.TUE])
        self.assertEqual(out[self.MON]["sales"], {})
        self.assertEqual(out[self.TUE]["sales"], {})

    def test_an_empty_window_day_is_present_not_missing(self):
        # A board needs to know a day was READ and was empty, which is not the
        # same as a day nobody looked at.
        out = B.tally_window([], [self.MON, self.TUE])
        self.assertEqual(sorted(out), [self.MON, self.TUE])
        self.assertEqual(out[self.MON], {"records": {}, "sales": {},
                                         "unknown": []})


class TheApiNamesAreNotTheScreenNames(unittest.TestCase):
    """Captured from the live page 2026-09-15. The grid heading is "Initiated
    Date" and the field on the wire is created_date; the agent is a nested
    object, not a string. A reader written off the column headings would have
    found neither."""

    EDGE = {
        "contract_id": 289270,
        "business_name": "KELLEY'S DAYCARE LLC",
        "adjusted_annual_volume": 51000,
        "created_date": "09/15/2026 04:58 PM",
        "agent": {"name": {"first_name": "Max", "last_name": "Allen"},
                  "email": "max@example.com"},
        "contract_substatus": {"substatus": "TPV Passed",
                               "substatus_alias": "tpv_passed"},
    }

    def test_an_edge_becomes_a_row_tally_can_read(self):
        row = B.row_from_edge(self.EDGE)
        self.assertEqual(row["Agent"], "Max Allen")
        self.assertEqual(row["Initiated Date"], "09/15/2026 04:58 PM")
        self.assertEqual(row["Contract Substatus"], "TPV Passed")
        self.assertEqual(row["Adjusted Annual Volume"], 51000)

    def test_it_feeds_straight_into_tally(self):
        out = B.tally([B.row_from_edge(self.EDGE)], DAY)
        self.assertEqual(out["sales"]["Max Allen"],
                         {"Sales": 1, "Volume": 51000})

    def test_a_missing_agent_does_not_invent_a_rep(self):
        edge = dict(self.EDGE, agent=None)
        self.assertEqual(B.row_from_edge(edge)["Agent"], "")
        self.assertEqual(B.tally([B.row_from_edge(edge)], DAY)["sales"], {})

    def test_a_half_named_agent_still_reads(self):
        edge = dict(self.EDGE,
                    agent={"name": {"first_name": "Cher", "last_name": None}})
        self.assertEqual(B.row_from_edge(edge)["Agent"], "Cher")


class APartialResponseIsNotAShortDay(unittest.TestCase):
    """An envelope carrying errors returns NOTHING rather than the edges that
    did arrive. A partial page read as a whole one is how an office's number
    comes out low with nothing to say why."""

    OK = {"data": {"contractsList": {"edges": [
        TheApiNamesAreNotTheScreenNames.EDGE]}}}

    def test_a_good_response_yields_rows(self):
        self.assertEqual(len(B.rows_from_response(self.OK)), 1)

    def test_top_level_errors_yield_nothing(self):
        bad = dict(self.OK, errors=[{"message": "boom"}])
        self.assertEqual(B.rows_from_response(bad), [])

    def test_envelope_errors_yield_nothing(self):
        bad = {"data": {"contractsList": {
            "edges": [TheApiNamesAreNotTheScreenNames.EDGE],
            "errors": [{"error_message": "partial"}]}}}
        self.assertEqual(B.rows_from_response(bad), [])

    def test_garbage_does_not_raise(self):
        for junk in (None, {}, {"data": None}, {"data": {"contractsList": None}}):
            self.assertEqual(B.rows_from_response(junk), [])


class TheScreenAndTheWireDisagreeAboutDates(unittest.TestCase):
    """The grid shows "09/15/2026 06:13 PM"; the API returns
    "2026-09-15 18:13:46" for the same contract.

    Parsing only the screen's format matched NOTHING against Ryan's live
    data -- no error, no rows, just an office that looked like it had sold
    nothing. A silent empty is the worst way for this to fail, because it is
    indistinguishable from a quiet day.
    """

    def test_the_api_format_reads(self):
        self.assertEqual(B.initiated_on("2026-09-15 18:13:46"), DAY)

    def test_the_screen_format_still_reads(self):
        self.assertEqual(B.initiated_on("09/15/2026 06:13 PM"), DAY)

    def test_live_api_rows_actually_tally(self):
        # The shape that came back empty before the fix.
        rows = [B.row_from_edge({
            "agent": {"name": {"first_name": "Max", "last_name": "Allen"}},
            "created_date": "2026-09-15 16:58:20",
            "contract_substatus": {"substatus": "TPV Passed"},
            "adjusted_annual_volume": 51000})]
        out = B.tally(rows, DAY)
        self.assertEqual(out["sales"]["Max Allen"],
                         {"Sales": 1, "Volume": 51000})

    def test_a_service_start_still_does_not_parse(self):
        self.assertIsNone(B.initiated_on("APR 2027"))
