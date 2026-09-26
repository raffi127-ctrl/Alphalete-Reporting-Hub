"""The week-over-week layout: find a metric by its LABEL and a week by its
HEADER DATE, never by position. A template someone re-orders by hand must not
start writing the show rate into the pay row.

  python -m unittest automations.sms_audit.test_weekly_sheet
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.sms_audit import analyze as A
from automations.sms_audit import weekly_sheet as W


class A1Test(unittest.TestCase):
    def test_columns_past_z_keep_counting(self):
        self.assertEqual(W._a1(2, 1), "A2")
        self.assertEqual(W._a1(2, 3), "C2")
        self.assertEqual(W._a1(10, 26), "Z10")
        self.assertEqual(W._a1(10, 27), "AA10")
        self.assertEqual(W._a1(1, 52), "AZ1")


class LabelLookupTest(unittest.TestCase):
    def test_a_metric_is_found_by_its_label_wherever_it_sits(self):
        values = [["Applicant text audit"],
                  ["", "", "09/18/26"],
                  ["Reach", "People texted", "100"],
                  ["", "", ""],                       # a gap somebody left
                  ["Booking", "Booked by the AI", "40"]]
        rows = W._label_rows(values)
        self.assertEqual(rows["People texted"], 3)
        self.assertEqual(rows["Booked by the AI"], 5)

    def test_a_blank_label_is_not_a_row(self):
        self.assertNotIn("", W._label_rows([["Reach", ""], ["", "  "]]))


class WeekColumnTest(unittest.TestCase):
    def test_week_headers_are_read_off_the_header_row(self):
        values = [["Applicant text audit"],
                  ["", "", "09/18/26", "09/25/26"],
                  ["Reach", "People texted", "100", "120"]]
        cols = W._week_columns(values)
        self.assertEqual(cols[dt.date(2026, 9, 18)], 3)
        self.assertEqual(cols[dt.date(2026, 9, 25)], 4)

    def test_the_label_columns_are_never_mistaken_for_a_week(self):
        # A and B hold text, not dates — but guard the boundary anyway, since a
        # stray date in B would otherwise become "the first week"
        values = [["x"], ["09/18/26", "09/25/26", "10/02/26"]]
        self.assertEqual(list(W._week_columns(values).values()), [3])

    def test_no_header_row_yet_means_no_weeks(self):
        self.assertEqual(W._week_columns([]), {})


class WriteWeekTest(unittest.TestCase):
    """Re-running a week must overwrite that week's column, not append a
    second one beside it — the audit gets re-run whenever a pull is repaired."""

    def _rep(self):
        import collections
        return {"office": "11280", "threads": 10, "questions_total": 4,
                "questions": collections.Counter({"Can we reschedule / a different time?": 3}),
                "mix": {"ai": 6, "human": 4}, "unanswered": [1, 2],
                "anomalies": {}, "log": None, "questions_other": [],
                "question_table": [], "messages": 0}

    def test_a_fresh_tab_lays_out_labels_and_one_week(self):
        ws = W._EmptyTab("11280 Rafael Hidalgo")
        col, _ = W.write_week(ws, self._rep(), dt.date(2026, 9, 25), dry_run=True)
        self.assertEqual(col, W.FIRST_WEEK_COL)

    def test_an_existing_week_reuses_its_column(self):
        class _Tab(W._EmptyTab):
            def get_all_values(self):
                rows = [["Applicant text audit"], ["", "", "09/18/26", "09/25/26"]]
                for section, label, _fn in W.ROWS:
                    rows.append([section, label, "", ""])
                return rows
        col, _ = W.write_week(_Tab("t"), self._rep(), dt.date(2026, 9, 25),
                              dry_run=True)
        self.assertEqual(col, 4)

    def test_a_new_week_lands_to_the_right_of_the_last_one(self):
        class _Tab(W._EmptyTab):
            def get_all_values(self):
                return [["Applicant text audit"], ["", "", "09/18/26", "09/25/26"]]
        col, _ = W.write_week(_Tab("t"), self._rep(), dt.date(2026, 10, 2),
                              dry_run=True)
        self.assertEqual(col, 5)


class BlankNotZeroTest(unittest.TestCase):
    """A metric with no source writes BLANK. Writing 0 would say "nobody was
    texted this week", which is a different and much worse claim."""

    def test_log_only_metrics_are_blank_without_a_log(self):
        rep = {"log": None, "threads": 5, "mix": {"ai": 2, "human": 3}}
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["People texted"](rep), "")
        self.assertEqual(by_label["Reply rate %"](rep), "")
        self.assertEqual(by_label["AI reply, median minutes"](rep), "")

    def test_a_rate_over_nothing_is_blank_not_zero(self):
        self.assertEqual(W._rate(0, 0), "")
        self.assertEqual(W._rate(None, 10), "")
        self.assertEqual(W._rate(1, 4), 25.0)

    def test_the_calendar_walk_still_fills_the_booking_rows(self):
        rep = {"log": None, "threads": 10, "mix": {"ai": 6, "human": 4}}
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["Booked a 1st interview"](rep), 10)
        self.assertEqual(by_label["Booked by the AI"](rep), 6)
        self.assertEqual(by_label["AI share of bookings %"](rep), 60.0)


class TabNameTest(unittest.TestCase):
    def test_one_tab_per_account_named_by_id_and_owner(self):
        names = {"11280": "Rafael Hidalgo"}
        self.assertEqual(W.tab_title("11280", names), "11280 Rafael Hidalgo")
        # Raf's other two streams are their own accounts, so their own tabs.
        # Their name is not in OFFICE_NAMES, so it comes off the push table's
        # `short` — three tabs all reading "Rafael Hidalgo" would be unreadable
        self.assertEqual(W.tab_title("23965", names), "23965 Rafael 2nd funnel")

    def test_one_owner_with_three_accounts_gets_three_tabs(self):
        # Raf owns 11280, 23965 and 24065 — keying the tab on the OWNER would
        # collapse all three into one and silently sum them
        names = {"11280": "Rafael Hidalgo", "23965": "Rafael Hidalgo",
                 "24065": "Rafael Hidalgo"}
        titles = {W.tab_title(o, names) for o in ("11280", "23965", "24065")}
        self.assertEqual(len(titles), 3)


if __name__ == "__main__":
    unittest.main()


class WindowGuardTest(unittest.TestCase):
    """The column header IS the claim. A Sep 2-4 pull filed under the column
    headed 09/25/26 does not just mislabel itself — next week's run finds that
    column already filled and the wrong numbers stay. Silent in both
    directions, so it is a hard stop, not a warning."""

    def _rep(self, dates):
        return {"office": "11580", "dates": dates}

    def test_data_inside_the_week_is_allowed(self):
        rep = self._rep(["09-19-2026", "09-22-2026", "09-25-2026"])
        self.assertIsNone(W.check_window(rep, dt.date(2026, 9, 25)))

    def test_data_from_another_week_is_refused(self):
        rep = self._rep(["09-02-2026", "09-04-2026"])
        msg = W.check_window(rep, dt.date(2026, 9, 25))
        self.assertIsNotNone(msg)
        self.assertIn("2026-09-02", msg)

    def test_a_window_spilling_one_day_past_the_friday_is_refused(self):
        rep = self._rep(["09-19-2026", "09-26-2026"])
        self.assertIsNotNone(W.check_window(rep, dt.date(2026, 9, 25)))

    def test_the_saturday_start_is_inside_the_week(self):
        # Sat 09-19 opens the week ending Fri 09-25 — an off-by-one here would
        # refuse every full-week pull
        rep = self._rep(["09-19-2026"])
        self.assertIsNone(W.check_window(rep, dt.date(2026, 9, 25)))

    def test_no_dates_cannot_be_checked_so_is_not_blocked(self):
        self.assertIsNone(W.check_window({"dates": []}, dt.date(2026, 9, 25)))

    def test_the_window_is_read_off_the_data_not_the_request(self):
        self.assertEqual(W.data_window(self._rep(["09-04-2026", "09-02-2026"])),
                         (dt.date(2026, 9, 2), dt.date(2026, 9, 4)))


class WeekHeaderTest(unittest.TestCase):
    """'WE 9/25' — week ending, the way recruiting says it (Megan). The header
    has to round-trip: next week's run finds this week's column by READING it
    back, so a header it cannot parse silently starts a duplicate column."""

    def test_the_header_reads_the_way_recruiting_says_it(self):
        self.assertEqual(W.week_header(dt.date(2026, 9, 25)), "WE 9/25")
        self.assertEqual(W.week_header(dt.date(2026, 10, 2)), "WE 10/2")

    def test_no_zero_padding_and_no_glibc_strftime(self):
        # %-m/%-d is glibc-only and every report here runs on Windows too
        self.assertEqual(W.week_header(dt.date(2026, 9, 4)), "WE 9/4")

    def test_it_round_trips(self):
        for d in (dt.date(2026, 9, 4), dt.date(2026, 9, 25), dt.date(2026, 10, 2)):
            self.assertEqual(W.parse_week_header(W.week_header(d)), d)

    def test_the_year_is_recovered_from_the_friday_rule(self):
        # a week-ending date is always a Friday, and a month/day only lands on
        # one every 6-11 years, so the short form is not ambiguous in practice
        self.assertEqual(W.parse_week_header("WE 9/25"), dt.date(2026, 9, 25))
        self.assertEqual(dt.date(2026, 9, 25).weekday(), 4)

    def test_older_header_spellings_still_resolve(self):
        # columns written before the format changed must keep their place
        self.assertEqual(W.parse_week_header("09/04/26"), dt.date(2026, 9, 4))
        self.assertEqual(W.parse_week_header("WE 9/25/26"), dt.date(2026, 9, 25))

    def test_a_label_is_not_a_week(self):
        for junk in ("People texted", "", "Reach", "Q: What is the pay?"):
            self.assertIsNone(W.parse_week_header(junk))


class QuestionCellTest(unittest.TestCase):
    """The whole ranked list lives in the WEEK'S OWN CELL (Megan), most asked
    first, with what we usually reply on the same line. Eleven fixed rows were
    unreadable and the reply had nowhere to go."""

    def _rep(self, table, other=0):
        return {"question_table": table, "questions_other": list(range(other)),
                "messages": 900, "log": None}

    def test_most_asked_comes_first(self):
        cell = W.question_cell(self._rep([
            {"question": "Can we reschedule / a different time?", "asked": 45,
             "reply": "1st Interview - Reschedule", "no_reply": 2},
            {"question": "What is the pay?", "asked": 2,
             "reply": "“Our HR manager…”", "no_reply": 0}]))
        self.assertLess(cell.index("reschedule"), cell.index("pay"))
        self.assertTrue(cell.startswith("45 x"))

    def test_the_reply_rides_with_its_question(self):
        cell = W.question_cell(self._rep([
            {"question": "What is the pay?", "asked": 2,
             "reply": "1st Interview - Reschedule", "no_reply": 0}]))
        self.assertIn("What is the pay?", cell)
        self.assertIn("-> 1st Interview - Reschedule", cell)

    def test_questions_that_got_no_reply_are_called_out(self):
        cell = W.question_cell(self._rep([
            {"question": "What is the pay?", "asked": 5, "reply": "x",
             "no_reply": 3}]))
        self.assertIn("(3 got no reply)", cell)

    def test_the_unbucketed_ones_are_the_last_line(self):
        cell = W.question_cell(self._rep(
            [{"question": "What is the pay?", "asked": 5, "reply": "x",
              "no_reply": 0}], other=49))
        self.assertTrue(cell.rstrip().endswith("49 x  (didn't fit a bucket)"))

    def test_a_week_with_no_questions_is_empty_not_a_header(self):
        self.assertEqual(W.question_cell(self._rep([])), "")


class NoMessagesIsBlankTest(unittest.TestCase):
    """A --bookings-only walk carries booking rows and no thread. Every
    message-derived metric then computes 0 — and 0 is a CLAIM ("nobody asked
    anything", "no texts went out at 7am"), not a measurement. Blank is the
    truth. This is the bug the first WE 9/25 column shipped with."""

    def _bookings_only(self):
        import collections
        return {"messages": 0, "log": None, "threads": 832,
                "mix": {"ai": 364, "human": 468},
                "questions": collections.Counter(), "questions_other": [],
                "questions_total": 0, "unanswered": [], "anomalies": {},
                "question_table": []}

    def test_questions_and_flags_are_blank_not_zero(self):
        rep = self._bookings_only()
        by_label = {label: fn for _s, label, fn in W.ROWS}
        for label in ("Questions asked", "Didn't fit a bucket",
                      "Most asked → what we usually reply",
                      "Left unanswered", "Texts outside 8am–9pm",
                      "Texted after they said stop", "Dead links sent"):
            self.assertEqual(by_label[label](rep), "", label)

    def test_the_booking_rows_are_still_real(self):
        rep = self._bookings_only()
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["Booked a 1st interview"](rep), 832)
        self.assertEqual(by_label["Booked by the AI"](rep), 364)

    def test_with_messages_a_zero_is_a_real_zero(self):
        import collections
        rep = self._bookings_only()
        rep["messages"] = 3164          # the walk DID read the threads
        by_label = {label: fn for _s, label, fn in W.ROWS}
        # nobody asked anything, and we read every message to find that out
        self.assertEqual(by_label["Questions asked"](rep), 0)
        self.assertEqual(by_label["Texts outside 8am–9pm"](rep), 0)


class ColumnOrderTest(unittest.TestCase):
    """Weeks read left to right in time. A backfilled week goes in its place,
    not on the end — otherwise the sheet reads 9/25 then 9/4."""

    def _rep(self):
        import collections
        return {"office": "11580", "threads": 10, "questions_total": 0,
                "questions": collections.Counter(), "questions_other": [],
                "mix": {"ai": 6, "human": 4}, "unanswered": [], "messages": 0,
                "anomalies": {}, "log": None}

    def test_an_older_week_lands_left_of_a_newer_one(self):
        class _Tab(W._EmptyTab):
            def get_all_values(self):
                return [["Applicant text audit"], ["", "", "WE 9/25"]]
        col, _ = W.write_week(_Tab("t"), self._rep(), dt.date(2026, 9, 4),
                              dry_run=True)
        self.assertEqual(col, 3)      # takes C, pushing WE 9/25 to D

    def test_the_newest_week_still_lands_on_the_end(self):
        class _Tab(W._EmptyTab):
            def get_all_values(self):
                return [["Applicant text audit"], ["", "", "WE 9/4", "WE 9/18"]]
        col, _ = W.write_week(_Tab("t"), self._rep(), dt.date(2026, 9, 25),
                              dry_run=True)
        self.assertEqual(col, 5)

    def test_a_middle_week_slots_between(self):
        class _Tab(W._EmptyTab):
            def get_all_values(self):
                return [["Applicant text audit"], ["", "", "WE 9/4", "WE 9/25"]]
        col, _ = W.write_week(_Tab("t"), self._rep(), dt.date(2026, 9, 18),
                              dry_run=True)
        self.assertEqual(col, 4)


class CoverageRowTest(unittest.TestCase):
    """Every column says which days it is built from. Carlos's WE 9/4 is three
    days and WE 9/25 is five, so 185 beside 373 reads like volume doubling
    when it is 3 days against 5. The window guard checks the data falls INSIDE
    the week; it cannot know what a full week should be."""

    def _rep(self, dates):
        return {"dates": dates}

    def test_it_names_the_day_count_and_the_span(self):
        cell = W.days_cell(self._rep(["09-02-2026", "09-03-2026", "09-04-2026"]))
        self.assertEqual(cell, "3 days · 9/2 – 9/4")

    def test_a_missing_saturday_shows_as_five_days(self):
        cell = W.days_cell(self._rep(["09-21-2026", "09-22-2026", "09-23-2026",
                                      "09-24-2026", "09-25-2026"]))
        self.assertTrue(cell.startswith("5 days"), cell)

    def test_a_full_week_says_six(self):
        cell = W.days_cell(self._rep(["09-19-2026", "09-21-2026", "09-22-2026",
                                      "09-23-2026", "09-24-2026", "09-25-2026"]))
        self.assertTrue(cell.startswith("6 days"), cell)

    def test_no_dates_is_blank_not_a_zero(self):
        self.assertEqual(W.days_cell(self._rep([])), "")

    def test_it_is_the_first_row_so_it_is_read_before_the_numbers(self):
        self.assertEqual(W.ROWS[0][1], "Interview days in this column")
