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
                  ["Reach", "People we texted", "100"],
                  ["", "", ""],                       # a gap somebody left
                  ["Booking", "…booked by the AI", "40"]]
        rows = W._label_rows(values)
        self.assertEqual(rows["People we texted"], 3)
        self.assertEqual(rows["…booked by the AI"], 5)

    def test_a_blank_label_is_not_a_row(self):
        self.assertNotIn("", W._label_rows([["Reach", ""], ["", "  "]]))


class WeekColumnTest(unittest.TestCase):
    def test_week_headers_are_read_off_the_header_row(self):
        values = [["Applicant text audit"],
                  ["", "", "09/18/26", "09/25/26"],
                  ["Reach", "People we texted", "100", "120"]]
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
        self.assertEqual(by_label["People we texted"](rep), "")
        self.assertEqual(by_label["% who texted back"](rep), "")
        self.assertEqual(by_label["Minutes for the AI to reply (typical)"](rep), "")

    def test_a_rate_over_nothing_is_blank_not_zero(self):
        self.assertEqual(W._rate(0, 0), "")
        self.assertEqual(W._rate(None, 10), "")
        self.assertEqual(W._rate(1, 4), 25.0)

    def test_the_calendar_walk_still_fills_the_booking_rows(self):
        rep = {"log": None, "threads": 10, "mix": {"ai": 6, "human": 4}}
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["Booked a 1st interview"](rep), 10)
        self.assertEqual(by_label["…booked by the AI"](rep), 6)
        self.assertEqual(by_label["% of bookings made by the AI"](rep), 60.0)


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
        for junk in ("People we texted", "", "Reach", "Q: What is the pay?"):
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
        self.assertTrue(cell.startswith("1. Can we reschedule"), cell)
        self.assertIn("asked 45x", cell)

    def test_the_reply_rides_with_its_question(self):
        cell = W.question_cell(self._rep([
            {"question": "What is the pay?", "asked": 2,
             "reply": "1st Interview - Reschedule", "no_reply": 0}]))
        self.assertIn("What is the pay?", cell)
        self.assertIn("1st Interview - Reschedule", cell)

    def test_questions_that_got_no_reply_are_called_out(self):
        cell = W.question_cell(self._rep([
            {"question": "What is the pay?", "asked": 5, "reply": "x",
             "no_reply": 3}]))
        self.assertIn("3 got no answer", cell)

    def test_the_unbucketed_ones_are_the_last_line(self):
        cell = W.question_cell(self._rep(
            [{"question": "What is the pay?", "asked": 5, "reply": "x",
              "no_reply": 0}], other=49))
        self.assertTrue(cell.rstrip().endswith("(didn't fit a bucket — 49x)"), cell)

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
        for label in ("Questions asked", "Questions we couldn't group",
                      "Most asked → what we usually reply",
                      "Applicants left waiting 2+ hours", "Texts sent before 8am or after 9pm",
                      "Texted after they said stop", "Broken links sent"):
            self.assertEqual(by_label[label](rep), "", label)

    def test_the_booking_rows_are_still_real(self):
        rep = self._bookings_only()
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["Booked a 1st interview"](rep), 832)
        self.assertEqual(by_label["…booked by the AI"](rep), 364)

    def test_with_messages_a_zero_is_a_real_zero(self):
        import collections
        rep = self._bookings_only()
        rep["messages"] = 3164          # the walk DID read the threads
        by_label = {label: fn for _s, label, fn in W.ROWS}
        # nobody asked anything, and we read every message to find that out
        self.assertEqual(by_label["Questions asked"](rep), 0)
        self.assertEqual(by_label["Texts sent before 8am or after 9pm"](rep), 0)


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
    """Every column says which days it is built from, against how many it
    should have. **Saturday books no first rounds** — second interviews run
    then (Megan 2026-09-26) — so a first-interview week is five days, Mon-Fri,
    and an empty Saturday is normal rather than a gap. Carlos's WE 9/4 is
    three of those five, so 185 beside 373 is not volume doubling."""

    def _rep(self, dates):
        return {"dates": dates}

    def test_five_weekdays_is_a_complete_week(self):
        cell = W.days_cell(self._rep(["09-21-2026", "09-22-2026", "09-23-2026",
                                      "09-24-2026", "09-25-2026"]))
        self.assertTrue(cell.startswith("5 of 5 weekdays"), cell)
        self.assertNotIn("missing", cell)

    def test_a_missing_weekday_is_named(self):
        cell = W.days_cell(self._rep(["09-02-2026", "09-03-2026", "09-04-2026"]),
                           dt.date(2026, 9, 4))
        self.assertTrue(cell.startswith("3 of 5 weekdays"), cell)
        self.assertIn("missing Mon 8/31, Tue 9/1", cell)

    def test_a_saturday_booking_shows_as_extra_not_as_the_norm(self):
        cell = W.days_cell(self._rep(["09-19-2026", "09-21-2026", "09-22-2026",
                                      "09-23-2026", "09-24-2026", "09-25-2026"]))
        self.assertTrue(cell.startswith("5 of 5 weekdays"), cell)
        self.assertIn("plus Sat 9/19", cell)

    def test_no_dates_is_blank_not_a_zero(self):
        self.assertEqual(W.days_cell(self._rep([])), "")

    def test_it_is_the_first_row_so_it_is_read_before_the_numbers(self):
        self.assertEqual(W.ROWS[0][1], "1st-interview days covered")


class PlainLabelTest(unittest.TestCase):
    """Megan, twice: "Applicants over the carrier limit — what does this
    mean?" and "median minutes / Person's reply — this verbiage is
    confusing". A label a non-technical person has to ask about is a broken
    label."""

    def test_no_statistician_words(self):
        for _sec, label, _fn in W.ROWS:
            low = label.lower()
            for word in ("median", "p90", "rate,", "carrier limit", "bucket",
                         "person's"):
                self.assertNotIn(word, low, label)

    def test_a_percent_row_says_what_of_what(self):
        for _sec, label, _fn in W.ROWS:
            if "%" in label:
                self.assertTrue(label.startswith("%") or "%" in label.split()[-1],
                                "{!r} does not read as a percentage of "
                                "something".format(label))


class RenameTest(unittest.TestCase):
    """Rewording a label has to RENAME the row, not add a new one and leave
    the old one holding real weeks above it."""

    def _rep(self):
        import collections
        return {"office": "11280", "threads": 10, "questions_total": 0,
                "questions": collections.Counter(), "questions_other": [],
                "mix": {"ai": 6, "human": 4}, "unanswered": [], "messages": 0,
                "anomalies": {}, "log": None, "question_table": [],
                "dates": ["09-25-2026"]}

    def test_every_old_label_points_at_a_live_one(self):
        live = {label for _s, label, _f in W.ROWS}
        for old, new in W.RENAMED.items():
            self.assertIn(new, live, "{} -> {} is not a row any more".format(old, new))
            self.assertNotIn(old, live, "{} is both old and current".format(old))

    def test_an_old_tab_gets_its_labels_rewritten_in_place(self):
        class _Tab(W._EmptyTab):
            def get_all_values(self):
                return [["Applicant text audit"], ["", "", "WE 9/18"],
                        ["Reach", "People texted", "100"],
                        ["Speed", "AI reply, median minutes", "1"]]
        col, _n = W.write_week(_Tab("t"), self._rep(), dt.date(2026, 9, 25),
                               dry_run=True)
        self.assertEqual(col, 4)   # the old week keeps its column


class PercentCellTest(unittest.TestCase):
    """A percentage cell shows "54.0%", not a bare 54 that reads like a count
    (Megan). It is stored as the FRACTION with a percent number format, so the
    value underneath is still a real number."""

    def test_the_percent_rows_are_the_ones_labelled_so(self):
        self.assertTrue(W.is_percent("% who texted back"))
        self.assertTrue(W.is_percent("% who showed — AI bookings"))
        self.assertFalse(W.is_percent("People we texted"))
        self.assertFalse(W.is_percent("Booked a 1st interview"))

    def test_a_percent_is_stored_as_its_fraction(self):
        import collections
        rep = {"log": None, "threads": 10, "mix": {"ai": 6, "human": 4},
               "messages": 0, "questions": collections.Counter(),
               "questions_other": [], "questions_total": 0, "unanswered": [],
               "anomalies": {}, "question_table": [], "dates": ["09-25-2026"]}

        class _Book(object):
            """The workbook-level batch_update (column widths) is a different
            call from the worksheet one; a stub that conflates them swallows
            the cell writes."""

            def batch_update(self, body, **kw):
                pass

        class _Tab(W._EmptyTab):
            id = 0

            def __init__(self):
                W._EmptyTab.__init__(self, "t")
                self.sent = []
                self.spreadsheet = _Book()

            def batch_update(self, data, **kw):
                self.sent = list(data)

            def resize(self, **kw):
                pass

            def format(self, *a, **kw):
                pass

            def freeze(self, **kw):
                pass

        tab = _Tab()
        W.write_week(tab, rep, dt.date(2026, 9, 25))
        by_range = {d["range"]: d["values"][0][0] for d in tab.sent}
        rows = {label: W._a1(i, 3) for i, (_s, label, _f)
                in enumerate(W.ROWS, start=W.HEADER_ROW + 1)}
        # 6 of 10 bookings are the AI's -> 60% stored as 0.6, not 60
        self.assertEqual(by_range[rows["% of bookings made by the AI"]], 0.6)
        self.assertEqual(by_range[rows["…booked by the AI"]], 6)

    def test_a_blank_percent_stays_blank_not_zero(self):
        import collections
        rep = {"log": None, "threads": 0, "mix": {"ai": 0, "human": 0},
               "messages": 0, "questions": collections.Counter(),
               "questions_other": [], "questions_total": 0, "unanswered": [],
               "anomalies": {}, "question_table": [], "dates": []}
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["% who texted back"](rep), "")
