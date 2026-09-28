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
from automations.shared import servicecloud as SC

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


class WorkingCountsEveryLiveContract(unittest.TestCase):
    """Megan 2026-09-15: the statuses MOVE, so a contract passes through the
    signature step on its way to a sale.

    "Working" is therefore every contract that has not died, and a sale is a
    subset of it -- not the other half of it. Counting them as either/or made
    a rep's working number FALL as their sales rose, and made the fast alert
    count only whoever happened to be parked at one step this minute.
    """

    def test_a_live_contract_counts_as_working(self):
        out = B.tally([_row("Sohaib Hafeez", "Awaiting Signature")], DAY)
        self.assertEqual(out["records"], {"Sohaib Hafeez": 1})
        self.assertEqual(out["sales"], {})

    def test_a_sale_is_working_AND_sold(self):
        out = B.tally([_row("Sohaib Hafeez", "TPV Passed")], DAY)
        self.assertEqual(out["records"]["Sohaib Hafeez"], 1,
                         "a sale stopped counting as work done")
        self.assertEqual(out["sales"]["Sohaib Hafeez"]["Sales"], 1)

    def test_a_dead_contract_counts_as_neither(self):
        out = B.tally([_row("Sohaib Hafeez", "Cancelled by Broker")], DAY)
        self.assertEqual(out["records"], {})
        self.assertEqual(out["sales"], {})

    def test_a_reps_day_adds_up(self):
        rows = [_row("Sohaib Hafeez", "Awaiting Signature"),
                _row("Sohaib Hafeez", "PDF Generated"),
                _row("Sohaib Hafeez", "TPV Passed", volume="10,099"),
                _row("Sohaib Hafeez", "Cancelled by Broker")]
        out = B.tally(rows, DAY)
        self.assertEqual(out["records"]["Sohaib Hafeez"], 3,
                         "three live contracts; the cancelled one is not work")
        self.assertEqual(out["sales"]["Sohaib Hafeez"],
                         {"Sales": 1, "Volume": 10099, "Big": 1, "Huge": 0})


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
                         {"Sales": 1, "Volume": 0, "Big": 1, "Huge": 0})

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

    def test_rereading_turns_working_into_sold_on_its_own_day(self):
        mon_row = _row("Max Allen", "Awaiting Signature",
                       when="09/14/2026 04:43 PM")
        first = B.tally_window([mon_row], [self.MON, self.TUE])
        self.assertEqual(first[self.MON]["records"]["Max Allen"], 1)
        self.assertEqual(first[self.MON]["sales"], {})

        # Wednesday's read: same contract, status has moved on. It is still
        # Monday's work AND now Monday's sale -- the working number must not
        # drop because a contract advanced.
        mon_row["Contract Substatus"] = "TPV Passed"
        second = B.tally_window([mon_row], [self.MON, self.TUE])
        self.assertEqual(second[self.MON]["sales"]["Max Allen"]["Sales"], 1)
        self.assertEqual(second[self.MON]["records"]["Max Allen"], 1)

    def test_a_contract_that_dies_leaves_both_numbers(self):
        # It was work on Monday and it is not any more.
        row = _row("Max Allen", "Awaiting Signature", when="09/14/2026 04:43 PM")
        row["Contract Substatus"] = "Cancelled by Broker"
        out = B.tally_window([row], [self.MON, self.TUE])
        self.assertEqual(out[self.MON]["records"], {})
        self.assertEqual(out[self.MON]["sales"], {})

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
                         {"Sales": 1, "Volume": 51000, "Big": 1, "Huge": 1})

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
                         {"Sales": 1, "Volume": 51000, "Big": 1, "Huge": 1})

    def test_a_service_start_still_does_not_parse(self):
        self.assertIsNone(B.initiated_on("APR 2027"))


class HowLoudIsDecidedPerContract(unittest.TestCase):
    """Carlos Hidalgo, 2026-09-15, asked what makes a Box sale worth shouting
    about:

        Normal: any sale
        Big:    24 month contract
        Huge:   24 month contract, 20k KWH +

    Two things in that had been got wrong here. The volume is ENERGY -- the
    order log's column is "Sales (All) kWH+Therms" -- and a contract has a
    TERM in months, which this reader was not reading at all.
    """

    def _one(self, term, volume):
        rows = [_row("Max Allen", "TPV Passed", volume=volume)]
        rows[0][SC.COL_TERM] = term
        return B.tally(rows, DAY)["sales"]["Max Allen"]

    def test_long_term_and_big_volume_is_huge(self):
        got = self._one(36, "51,000")
        self.assertEqual((got["Big"], got["Huge"]), (1, 1))

    def test_long_term_alone_is_big(self):
        got = self._one(36, "900")
        self.assertEqual((got["Big"], got["Huge"]), (1, 0))

    def test_a_short_contract_is_neither_however_large(self):
        got = self._one(12, "99,000")
        self.assertEqual((got["Big"], got["Huge"]), (0, 0))
        self.assertEqual(got["Sales"], 1, "it is still a sale")

    def test_twenty_four_months_is_the_bar_itself(self):
        self.assertEqual(self._one(24, "20,000")["Huge"], 1)
        self.assertEqual(self._one(23, "20,000")["Big"], 0)

    def test_a_missing_term_stays_loud_rather_than_going_quiet(self):
        """If the API stops sending a term, failing every contract would read
        as ordinary and the channel would flatten with nothing reporting a
        fault. Too loud is visible; too quiet is not."""
        rows = [_row("Max Allen", "TPV Passed", volume="51,000")]
        rows[0].pop(SC.COL_TERM, None)
        self.assertEqual(B.tally(rows, DAY)["sales"]["Max Allen"]["Huge"], 1)

    def test_volume_is_never_added_to_a_count(self):
        from automations.shared import sale_hype as H
        m = {"Sales": 2, "Volume": 69248, "Big": 2, "Huge": 1}
        self.assertEqual(H.rep_total(m, "b2b_box"), 2,
                         "a rep just scored sixty-nine thousand sales")

    def test_the_line_gets_louder_by_carloss_rule(self):
        from automations.shared import sale_hype as H
        say = lambda m: H.tier(m, "b2b_box")
        self.assertEqual(say({"Sales": 1, "Volume": 900, "Big": 0, "Huge": 0}),
                         "regular")
        self.assertEqual(say({"Sales": 1, "Volume": 900, "Big": 1, "Huge": 0}),
                         "large")
        self.assertEqual(say({"Sales": 1, "Volume": 51000, "Big": 1, "Huge": 1}),
                         "super")

    def test_the_breakdown_says_kwh_not_dollars(self):
        from automations.shared import sale_hype as H
        said = H.breakdown({"Sales": 1, "Volume": 51000, "Big": 1, "Huge": 1},
                           "b2b_box")
        self.assertIn("51,000", said)
        self.assertIn("kWh", said)
        self.assertNotIn("$", said)


class TheAccountsProbeReadsIntrospection(unittest.TestCase):
    """The schema probe (Ryan 2026-09-28) must unwrap GraphQL type wrappers,
    never confuse an error envelope with an answer, and never carry data."""

    def test_short_tells_an_error_from_data_and_keeps_only_keys(self):
        self.assertTrue(B._short({"errors": [{"message": "Cannot query field x"}]}).startswith("ERR"))
        ok = B._short({"data": {"contractsList": {"edges": [{"contract_id": 4471, "business_name": "WHATACARS"}]}}})
        self.assertTrue(ok.startswith("OK"))
        self.assertNotIn("WHATACARS", ok)
        self.assertNotIn("4471", ok)
        self.assertIn("no data", B._short({"_status": 401}))

    def test_candidates_never_touch_the_live_query(self):
        for cand in B.PROBE_CANDIDATES:
            self.assertNotIn(cand, B.GRAPHQL_QUERY)


class AContractWithSeveralAccountsIsSeveralSales(unittest.TestCase):
    """Ryan 2026-09-28: Max's WHATACARS contract covers two meters and counts
    as two contracts. The volume is the contract's and is added once."""

    DAY = dt.date(2026, 9, 28)

    def _row(self, accounts, status="Sold - Completed"):
        return {SC.COL_AGENT: "Max Allen", SC.COL_INITIATED: "09/28/2026 12:28 PM",
                SC.COL_SUBSTATUS: status, "Adjusted Annual Volume": 17000,
                SC.COL_TERM: 12, B.COL_ACCOUNTS: accounts}

    def _sold(self):
        return next(s for s in SC.COMPLETED_STATUSES)

    def test_two_accounts_are_two_sales_and_one_volume(self):
        got = B.tally([self._row(2, self._sold())], self.DAY)
        self.assertEqual(got["sales"]["Max Allen"]["Sales"], 2)
        self.assertEqual(got["sales"]["Max Allen"]["Volume"], 17000)
        self.assertEqual(got["records"]["Max Allen"], 2)

    def test_a_row_without_the_count_is_still_one(self):
        row = self._row(None, self._sold()); row.pop(B.COL_ACCOUNTS)
        got = B.tally([row], self.DAY)
        self.assertEqual(got["sales"]["Max Allen"]["Sales"], 1)
        for bad in ("", "0", "x", -3):
            self.assertEqual(B._accounts({B.COL_ACCOUNTS: bad}), 1)

    def test_tiers_stay_per_contract(self):
        row = self._row(3, self._sold()); row[SC.COL_TERM] = 36; row["Adjusted Annual Volume"] = 25000
        got = B.tally([row], self.DAY)
        self.assertEqual(got["sales"]["Max Allen"]["Sales"], 3)
        self.assertEqual(got["sales"]["Max Allen"]["Big"], 1)
        self.assertEqual(got["sales"]["Max Allen"]["Huge"], 1)


class TheLiveReadCarriesTheAccountCount(unittest.TestCase):
    """Round 1 of the probe proved `accounts { account_number }` on the edge.
    The row carries the COUNT; the numbers never leave the machine."""

    def _edge(self, accounts):
        return {"contract_id": 1, "accounts": accounts, "business_name": "X",
                "adjusted_annual_volume": 17000, "created_date": "09/28/2026 12:28 PM",
                "term": 12, "agent": {"name": {"first_name": "Max", "last_name": "Allen"}},
                "contract_substatus": {"substatus": "TPV Passed"}}

    def test_two_accounts_count_two_and_carry_no_numbers(self):
        row = B.row_from_edge(self._edge([{"account_number": "1044"}, {"account_number": "1045"}]))
        self.assertEqual(row[B.COL_ACCOUNTS], 2)
        self.assertNotIn("1044", str(row))

    def test_the_customers_accounts_win_because_the_rows_own_list_is_never_filled(self):
        e = self._edge(None)
        e["customer"] = {"accounts": [{"account_number": "a"}, {"account_number": "b"}, {"account_number": "c"}]}
        self.assertEqual(B.row_from_edge(e)[B.COL_ACCOUNTS], 3)
        e["customer"] = {"accounts": None}
        self.assertEqual(B.row_from_edge(e)[B.COL_ACCOUNTS], "")

    def test_null_accounts_is_blank_which_reads_as_one(self):
        row = B.row_from_edge(self._edge(None))
        self.assertEqual(row[B.COL_ACCOUNTS], "")
        self.assertEqual(B._accounts(row), 1)

    def test_legacy_query_has_no_accounts_and_the_new_one_does(self):
        self.assertIn("customer { accounts { account_number } }", B.GRAPHQL_QUERY)
        self.assertNotIn("accounts", B.GRAPHQL_QUERY_LEGACY)
        self.assertTrue(B.payload_ok({"data": {"contractsList": {"edges": []}}}))
        self.assertFalse(B.payload_ok({"errors": [{"message": "Cannot query field"}]}))

    def test_a_refused_accounts_field_falls_back_to_the_old_query(self):
        calls = []

        class Res:
            ok = True
            status = 200
            def __init__(self, payload): self._p = payload
            def json(self): return self._p

        class Req:
            def post(self, url, headers=None, data=None):
                calls.append(data["query"])
                if "accounts" in data["query"]:
                    return Res({"errors": [{"message": "Cannot query field accounts"}]})
                return Res({"data": {"contractsList": {"edges": [
                    {"contract_id": 1, "created_date": "09/28/2026 12:28 PM",
                     "agent": {"name": {"first_name": "Max", "last_name": "Allen"}},
                     "contract_substatus": {"substatus": "TPV Passed"}}], "errors": []}}})

        class Page:
            request = Req()

        B._LEGACY["on"] = False
        try:
            rows = B._fetch_page(Page(), 1, None, log=lambda *a: None)
        finally:
            B._LEGACY["on"] = False
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][B.COL_ACCOUNTS], "")
        self.assertEqual(len(calls), 2)
        self.assertIn("accounts", calls[0]); self.assertNotIn("accounts", calls[1])

    def test_the_counts_report_is_counts_only(self):
        rows = [{B.COL_ACCOUNTS: 2, SC.COL_CONTRACT_ID: 4471}, {B.COL_ACCOUNTS: 1}, {B.COL_ACCOUNTS: ""}, {B.COL_ACCOUNTS: 1}]
        self.assertEqual(B.account_count_report(rows), "4 rows: 1=2, 2=1, blank=1; multi: 4471x2")
