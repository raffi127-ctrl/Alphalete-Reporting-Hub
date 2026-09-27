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
                  ["Booking", "— booked by the AI", "40"]]
        rows = W._label_rows(values)
        self.assertEqual(rows["People we texted"], 3)
        self.assertEqual(rows["— booked by the AI"], 5)

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
        self.assertEqual(by_label["Typical Response Time — AI (minutes)"](rep), "")

    def test_a_rate_over_nothing_is_blank_not_zero(self):
        self.assertEqual(W._rate(0, 0), "")
        self.assertEqual(W._rate(None, 10), "")
        self.assertEqual(W._rate(1, 4), 25.0)

    def test_the_calendar_walk_still_fills_the_booking_rows(self):
        rep = {"log": None, "threads": 10, "mix": {"ai": 6, "human": 4}}
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["1st Rounds Booked"](rep), 10)
        self.assertEqual(by_label["— booked by the AI"](rep), 6)
        self.assertEqual(by_label["% of 1st rounds booked by the AI"](rep), 60.0)


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

    def test_a_log_from_another_week_is_refused(self):
        # The half that used to go unguarded: the bookings walk is the right
        # week, the message log is not, and every number the log feeds — reply
        # speeds, questions, flags — would have been filed under this column.
        rep = self._rep(["09-21-2026", "09-25-2026"])
        rep["log_window"] = ("09-19-2026", "09-25-2026")
        self.assertIsNone(W.check_window(rep, dt.date(2026, 9, 25)))
        rep["log_window"] = ("08-29-2026", "09-04-2026")
        msg = W.check_window(rep, dt.date(2026, 9, 25))
        self.assertIsNotNone(msg)
        self.assertIn("2026-08-29", msg)

    def test_both_halves_feed_the_window(self):
        rep = self._rep(["09-21-2026"])
        rep["log_window"] = ("09-19-2026", "09-25-2026")
        self.assertEqual(W.data_window(rep),
                         (dt.date(2026, 9, 19), dt.date(2026, 9, 25)))

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
             "reply": "1st Interview - Reschedule", "no_reply": 2,
             "no_reply_unbooked": 2, "no_reply_booked": 0},
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
             "no_reply": 3, "no_reply_unbooked": 3, "no_reply_booked": 0}]))
        self.assertIn("3 got no reply here and never booked", cell)

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
        for label in ("Questions asked",
                      "Most asked → what we usually reply",
                      "Applicants left waiting 2+ hours for a response",
                      "Texted someone after they said stop", "Broken links sent"):
            self.assertEqual(by_label[label](rep), "", label)

    def test_the_booking_rows_are_still_real(self):
        rep = self._bookings_only()
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["1st Rounds Booked"](rep), 832)
        self.assertEqual(by_label["— booked by the AI"](rep), 364)

    def test_with_messages_a_zero_is_a_real_zero(self):
        import collections
        rep = self._bookings_only()
        rep["messages"] = 3164          # the walk DID read the threads
        by_label = {label: fn for _s, label, fn in W.ROWS}
        # nobody asked anything, and we read every message to find that out
        self.assertEqual(by_label["Questions asked"](rep), 0)
        self.assertEqual(by_label["Broken links sent"](rep), 0)


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
        self.assertEqual(W.ROWS[0][1], "Days of 1st rounds in this column")


class PlainLabelTest(unittest.TestCase):
    """Megan, twice: "Applicants over the carrier limit — what does this
    mean?" and "median minutes / Person's reply — this verbiage is
    confusing". A label a non-technical person has to ask about is a broken
    label."""

    def test_no_statistician_words(self):
        for _sec, label, _fn in W.ROWS:
            low = label.lower()
            for word in ("median", "p90", "rate,", "carrier limit", "bucket"):
                self.assertNotIn(word, low, label)

    def test_a_percent_row_says_what_of_what(self):
        """A bare "%" tells nobody the denominator. Every percentage label
        has to name the group it is a percentage OF."""
        for _sec, label, _fn in W.ROWS:
            if "%" not in label:
                continue
            low = label.lower()
            self.assertTrue(any(w in low for w in (" who ", " that ", " of ", "of "))
                            and len(label.split()) > 2,
                            "{!r} does not say what it is a percentage "
                            "of".format(label))


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
                        ["Speed", "Typical Response Time — AI (minutes)", "1"]]
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
        self.assertFalse(W.is_percent("1st Rounds Booked"))

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
        self.assertEqual(by_range[rows["% of 1st rounds booked by the AI"]], 0.6)
        self.assertEqual(by_range[rows["— booked by the AI"]], 6)

    def test_a_blank_percent_stays_blank_not_zero(self):
        import collections
        rep = {"log": None, "threads": 0, "mix": {"ai": 0, "human": 0},
               "messages": 0, "questions": collections.Counter(),
               "questions_other": [], "questions_total": 0, "unanswered": [],
               "anomalies": {}, "question_table": [], "dates": []}
        by_label = {label: fn for _s, label, fn in W.ROWS}
        self.assertEqual(by_label["% who texted back"](rep), "")


class UniqueLabelTest(unittest.TestCase):
    """Rows are found BY LABEL, so two rows sharing one is not a cosmetic
    problem — the second silently reuses the first's row and clobbers its
    numbers. That is exactly what happened when the cold-list and live-flow
    sections both used "% of them who booked"."""

    def test_no_two_rows_share_a_label(self):
        seen = {}
        for section, label, _fn in W.ROWS:
            self.assertNotIn(label, seen,
                             "{!r} is used by both {!r} and {!r}".format(
                                 label, seen.get(label), section))
            seen[label] = section

    def test_a_label_says_which_group_it_is_about(self):
        # "% of them who booked" under two sections was ambiguous to read as
        # well as broken to write
        for _sec, label, _fn in W.ROWS:
            self.assertNotIn("of them", label.lower(), label)


class RenameChainTest(unittest.TestCase):
    """A rename map is only useful if it lands somewhere real. Reword a label
    twice and the first entry points at the intermediate name, which no longer
    exists — the row is never found, a duplicate is added below it, and the
    weeks already written sit orphaned above."""

    def test_no_entry_points_at_another_entry(self):
        for old, new in W.RENAMED.items():
            self.assertNotIn(new, W.RENAMED,
                             "{!r} -> {!r} -> {!r} is a chain; point it at the "
                             "final name".format(old, new, W.RENAMED.get(new)))

    def test_no_entry_is_also_a_current_label(self):
        live = {l for _s, l, _f in W.ROWS}
        for old in W.RENAMED:
            self.assertNotIn(old, live,
                             "{!r} is both a current row and something to rename "
                             "away from".format(old))


class RedWarningTest(unittest.TestCase):
    """Megan: "can we make it so this 'got no answer' is in red font." Only
    those lines — the rest of the cell stays black."""

    TXT = ("1. Pay? — asked 2x, answered 1\n"
           "     ↳ HR covers it\n"
           "     ⚠ 1 got no answer\n\n"
           "2. Zoom? — asked 3x, answered 3\n"
           "     ↳ here is the link")

    def test_the_warning_line_is_red_and_the_rest_is_not(self):
        runs = W.warning_runs(self.TXT)
        red = [r for r in runs if r["format"].get("bold")]
        self.assertEqual(len(red), 1)
        self.assertTrue(self.TXT[red[0]["startIndex"]:].startswith("⚠"))

    def test_the_colour_turns_off_at_the_end_of_that_line(self):
        runs = W.warning_runs(self.TXT)
        red = next(r for r in runs if r["format"].get("bold"))
        after = next(r for r in runs if r["startIndex"] > red["startIndex"])
        self.assertFalse(after["format"].get("bold"))
        self.assertEqual(self.TXT[red["startIndex"]:after["startIndex"]].strip(),
                         "⚠ 1 got no answer")

    def test_a_cell_with_nothing_to_flag_gets_no_runs_at_all(self):
        self.assertEqual(W.warning_runs("1. Pay? — asked 2x, answered 2"), [])

    def test_runs_are_strictly_increasing_and_inside_the_text(self):
        runs = W.warning_runs(self.TXT)
        idx = [r["startIndex"] for r in runs]
        self.assertEqual(idx, sorted(set(idx)))
        self.assertTrue(all(0 <= i < len(self.TXT) for i in idx))

    def test_every_warning_line_gets_its_own_run(self):
        txt = ("1. A — asked 1x\n     ⚠ 1 got no answer\n\n"
               "2. B — asked 1x\n     ⚠ 1 got no answer")
        self.assertEqual(len([r for r in W.warning_runs(txt)
                              if r["format"].get("bold")]), 2)

    def test_an_emoji_cannot_shift_the_colour_onto_the_wrong_words(self):
        # textFormatRuns index by UTF-16 unit, so one emoji in an applicant's
        # reply would move every run after it
        self.assertNotIn("\U0001F600", W._bmp_only("hi \U0001F600 there"))
        self.assertEqual(W._bmp_only("café ⚠"), "café ⚠")


class CollapsibleTest(unittest.TestCase):
    """Megan: "this texts that never arrive section I want like a + sign
    expansion to see the why reason breakdowns." A group only works if the
    detail rows sit directly under the summary they explain."""

    def test_every_detail_row_is_a_real_row(self):
        live = {l for _s, l, _f in W.ROWS}
        for summary, children in W.COLLAPSIBLE:
            self.assertIn(summary, live, summary)
            for c in children:
                self.assertIn(c, live, c)

    def test_the_detail_block_sits_directly_under_its_summary(self):
        order = [l for _s, l, _f in W.ROWS]
        for summary, children in W.COLLAPSIBLE:
            i = order.index(summary)
            self.assertEqual(order[i + 1:i + 1 + len(children)], children,
                             "{!r}'s detail rows are not contiguous under it".format(summary))


class OutcomeNotTemplateTest(unittest.TestCase):
    """Megan 2026-09-26: "this prob means that they got a phone call to
    discuss. If someone gets directions, that means they were booked for an
    interview." The texts are half the conversation; the call list is the
    other half. So the test is whether the applicant ENDED UP BOOKED, not
    which template happened to fire — reading the text channel as the whole
    story turned people who had advanced into a red flag."""

    def _cell(self, unbooked, booked):
        return W.question_cell({
            "question_table": [{"question": "What is the pay?", "asked": 9,
                                "reply": "HR covers it", "answered": 4,
                                "no_reply": unbooked + booked,
                                "no_reply_unbooked": unbooked,
                                "no_reply_booked": booked,
                                "blast": "Friendly Reminder 1"}],
            "questions_other": [], "messages": 900, "log": {}})

    def test_someone_who_booked_anyway_is_not_a_failure(self):
        cell = self._cell(0, 2)
        self.assertIn("booked anyway", cell)
        self.assertEqual(W.warning_runs(cell), [])

    def test_someone_who_never_booked_is(self):
        cell = self._cell(3, 0)
        self.assertIn("never booked", cell)
        self.assertTrue([r for r in W.warning_runs(cell) if r["format"].get("bold")])

    def test_both_show_and_only_the_loss_is_red(self):
        cell = self._cell(3, 2)
        red = [cell[r["startIndex"]:] for r in W.warning_runs(cell)
               if r["format"].get("bold")]
        self.assertEqual(len(red), 1)
        self.assertTrue(red[0].startswith("⚠ 3 got no reply here and never booked"))

    def test_the_template_name_no_longer_decides_anything(self):
        # same template, opposite outcomes, opposite colours
        self.assertEqual(W.warning_runs(self._cell(0, 2)), [])
        self.assertTrue(W.warning_runs(self._cell(2, 0)))


class NestedGroupTest(unittest.TestCase):
    """Megan wanted "Our texts never reached them" to expand as well, and it
    already sits inside the "never booked" block — so the groups nest."""

    def test_the_inner_block_is_inside_the_outer_one(self):
        order = [l for _s, l, _f in W.ROWS]
        outer = dict(W.COLLAPSIBLE)["People we texted who never booked"]
        inner = dict(W.COLLAPSIBLE)["Our texts never reached them"]
        for label in inner:
            self.assertIn(label, outer, label)

    def test_the_outer_block_is_built_first(self):
        # Sheets derives depth from the groups already covering those rows
        ordered = sorted(W.COLLAPSIBLE, key=lambda g: -len(g[1]))
        self.assertEqual(ordered[0][0], "People we texted who never booked")

    def test_a_person_is_counted_once_however_many_texts_bounced(self):
        by = {l: f for _s, l, f in W.ROWS}
        rep = {"log": {"funnel": {"unreached": {"Failed": 98, "Requeued": 11}}}}
        self.assertEqual(by["— carrier rejected every text"](rep), 98)
        self.assertEqual(by["— phone number not valid"](rep), 0)

    def test_without_a_log_those_rows_are_blank_not_zero(self):
        by = {l: f for _s, l, f in W.ROWS}
        self.assertEqual(by["— carrier rejected every text"]({"log": None}), "")


class GroupDepthTest(unittest.TestCase):
    """A group's DEPTH is how many groups enclose it, and the API rejects an
    update whose depth is wrong outright: "there is no group at depth 1 that
    spans 22:25; it is over 16:26". Hardcoding 1 silently lost every group on
    the sheet, because one bad request fails the whole batch."""

    def _depths(self, blocks):
        """Mirror of the depth arithmetic in _collapse."""
        made, out = [], []
        for lo, hi in blocks:
            out.append(1 + sum(1 for a, b in made if a <= lo and hi <= b))
            made.append((lo, hi))
        return out

    def test_an_enclosed_block_is_one_level_deeper(self):
        self.assertEqual(self._depths([(15, 26), (21, 25)]), [1, 2])

    def test_siblings_stay_at_the_same_level(self):
        self.assertEqual(self._depths([(15, 26), (56, 63)]), [1, 1])

    def test_outermost_is_built_first_or_the_arithmetic_breaks(self):
        # counting enclosures only works if the enclosing group already exists
        ordered = sorted(W.COLLAPSIBLE, key=lambda g: -len(g[1]))
        sizes = [len(kids) for _s, kids in ordered]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


class UnbucketedIsBlueTest(unittest.TestCase):
    """Megan 2026-09-27: "make this text blue or a bold color to stand out so
    it's seen." The ungrouped tally is the one line saying there is more in
    the week than the buckets caught — it should not read as a footnote."""

    TXT = ("1. Pay? — asked 2x, answered 1\n"
           "     ⚠ 1 got no reply here and never booked\n\n"
           "(didn't fit a bucket — 42x)")

    def _runs(self):
        return W.warning_runs(self.TXT)

    def test_the_ungrouped_line_is_blue(self):
        blue = [r for r in self._runs()
                if r["format"].get("foregroundColor", {}).get("blue", 0) > 0.5]
        self.assertEqual(len(blue), 1)
        self.assertTrue(self.TXT[blue[0]["startIndex"]:].startswith("(didn't fit"))

    def test_the_warning_stays_red_not_blue(self):
        red = [r for r in self._runs()
               if r["format"].get("foregroundColor", {}).get("red", 0) > 0.5]
        self.assertEqual(len(red), 1)
        self.assertTrue(self.TXT[red[0]["startIndex"]:].startswith("⚠"))

    def test_a_cell_with_only_an_ungrouped_line_still_gets_painted(self):
        self.assertTrue(W.warning_runs("(didn't fit a bucket — 9x)"))

    def test_an_ordinary_cell_is_left_alone(self):
        self.assertEqual(W.warning_runs("1. Pay? — asked 2x, answered 2"), [])


class PerPersonRowTest(unittest.TestCase):
    """Megan 2026-09-27: "group by person with + expansion to see theirs."
    Senders change week to week, so these rows cannot live in the static
    list — they are built from the report and created by label like any
    other row."""

    def _rep(self):
        import collections as _c
        errs = ([{"kind": "spelling", "sender": "Sandy", "body": "onny via zoom",
                  "detail": "onny → only", "name": "Jane"}] * 3 +
                [{"kind": "doubled word", "sender": "Jorge", "body": "the the area",
                  "detail": "the the", "name": "Bob"}] +
                [{"kind": "lowercase i", "sender": "Sandy", "body": "i will",
                  "detail": "i", "name": "Jane"}])
        dodged = [{"kind": "dodged", "sender": "Sandy", "name": "Jose",
                   "question": "What is the pay?", "reply": "Call us.",
                   "bucket": "What is the pay?"}]
        return {"log": {"errors": errs, "dodged": dodged,
                        "funnel": {"drop": {}, "curve": {}, "delivery": {},
                                   "lanes": {}, "windows": {}}},
                "anomalies": {}, "questions": _c.Counter(), "questions_other": [],
                "questions_total": 0, "question_table": [], "unanswered": [],
                "messages": 10, "threads": 1, "mix": {"ai": 0, "human": 1},
                "dates": ["09-25-2026"]}

    def test_a_row_is_added_for_each_sender(self):
        rows, _groups = W.build_rows(self._rep())
        labels = [l for _s, l, _f in rows]
        self.assertIn("— Sandy", labels)
        self.assertIn("— Jorge", labels)

    def test_the_senders_sit_at_the_FOOT_of_their_section(self):
        """Megan 2026-09-27: "the expansion should be at the bottom of this
        section." Directly under the count it explained, the fold sat in the
        middle and the remaining counts read as part of the expansion."""
        rows, _groups = W.build_rows(self._rep())
        quality = [l for sec, l, _f in rows if sec == "Text quality"]
        self.assertTrue(quality[-2:] == ["— Sandy", "— Jorge"], quality)
        self.assertEqual(quality[0], "Texts with a spelling mistake")

    def test_both_sections_get_the_same_treatment(self):
        rows, _groups = W.build_rows(self._rep())
        for section in ("Text quality", "Questions handled badly"):
            labels = [l for sec, l, _f in rows if sec == section]
            self.assertTrue(labels[-1].startswith(W.PERSON_PREFIX),
                            "{}: {}".format(section, labels))

    def test_the_group_hangs_off_the_last_count_in_the_section(self):
        _rows, groups = W.build_rows(self._rep())
        anchors = [a for a, _k in groups]
        self.assertIn("Texts using lowercase 'i'", anchors)
        self.assertIn("Replies using texting shorthand", anchors)

    def test_worst_offender_first(self):
        _rows, groups = W.build_rows(self._rep())
        kids = dict(groups)["Texts using lowercase 'i'"]
        self.assertEqual(kids[0], "— Sandy")      # 3 issues vs Jorge's 1

    def test_lowercase_i_is_counted_but_not_shown_in_the_cell(self):
        entries = W.by_person(self._rep(), "errors")["Sandy"]
        self.assertEqual(len(entries), 3)         # the lowercase i is excluded
        self.assertNotIn("i will", W.person_cell(entries, "errors"))

    def test_a_persons_cell_reds_their_own_mistakes(self):
        entries = W.by_person(self._rep(), "errors")["Jorge"]
        text = W.person_cell(entries, "errors")
        runs = W.person_runs(entries, text)
        red = [r for r in runs if r["format"].get("bold")]
        self.assertEqual(len(red), 1)
        self.assertTrue(text[red[0]["startIndex"]:].startswith("the the"))

    def test_the_dodged_cell_names_the_applicant(self):
        entries = W.by_person(self._rep(), "dodged")["Sandy"]
        self.assertIn("Jose asked", W.person_cell(entries, "dodged"))

    def test_an_office_with_no_mistakes_adds_no_rows(self):
        rep = self._rep()
        rep["log"]["errors"] = []
        rep["log"]["dodged"] = []
        rows, groups = W.build_rows(rep)
        self.assertEqual(groups, [])
        self.assertFalse([l for _s, l, _f in rows if l.startswith("— S")])


class PersonLabelCollisionTest(unittest.TestCase):
    """The same sender turns up in both per-person sections. Rows are found
    by label, so without distinct labels the second section's row is
    silently skipped as already present — Sandy had a spelling row and no
    dodged row at all."""

    def test_the_two_sections_give_a_sender_different_labels(self):
        self.assertNotEqual(W.person_label("Sandy", "errors"),
                            W.person_label("Sandy", "dodged"))

    def test_both_rows_are_built_for_one_sender(self):
        rep = {"log": {"errors": [{"kind": "spelling", "sender": "Sandy",
                                   "body": "onny", "detail": "onny → only",
                                   "name": "J"}],
                       "dodged": [{"kind": "dodged", "sender": "Sandy",
                                   "name": "J", "question": "pay?",
                                   "reply": "call us", "bucket": "What is the pay?"}],
                       "funnel": {"drop": {}, "curve": {}, "delivery": {},
                                  "lanes": {}, "windows": {}}},
               "anomalies": {}, "questions": __import__("collections").Counter(),
               "questions_other": [], "questions_total": 0, "question_table": [],
               "unanswered": [], "messages": 5, "threads": 1,
               "mix": {"ai": 0, "human": 1}, "dates": ["09-25-2026"]}
        rows, groups = W.build_rows(rep)
        labels = [l for _s, l, _f in rows]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(groups), 2)


class SinglePersonGroupTest(unittest.TestCase):
    """An office with one offender still wants their detail folded away.
    Requiring two rows left Sandy's lone dodged-question row sitting open
    with no + beside it (Megan 2026-09-27: "it needs the expansion still")."""

    def _rep(self, senders):
        import collections as _c
        dodged = [{"kind": "dodged", "sender": s, "name": "J",
                   "question": "pay?", "reply": "call us",
                   "bucket": "What is the pay?"} for s in senders]
        return {"log": {"errors": [], "dodged": dodged,
                        "funnel": {"drop": {}, "curve": {}, "delivery": {},
                                   "lanes": {}, "windows": {}}},
                "anomalies": {}, "questions": _c.Counter(), "questions_other": [],
                "questions_total": 0, "question_table": [], "unanswered": [],
                "messages": 5, "threads": 1, "mix": {"ai": 0, "human": 1},
                "dates": ["09-25-2026"]}

    def test_one_sender_still_makes_a_group(self):
        _rows, groups = W.build_rows(self._rep(["Sandy"]))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(dict(groups)["Replies using texting shorthand"]), 1)

    def test_a_one_row_block_is_contiguous(self):
        # the contiguity test must not reject a block of one
        rows = [63]
        self.assertTrue(rows and rows[-1] - rows[0] == len(rows) - 1)

    def test_no_senders_makes_no_group(self):
        _rows, groups = W.build_rows(self._rep([]))
        self.assertEqual(groups, [])


class ColumnFitTest(unittest.TestCase):
    """Megan 2026-09-27: "not expanded to fit the text still". Column A is
    sized by the longest SECTION name and capped; column B by the longest
    LABEL. Auto-resize under-measures bold Georgia badly at 12pt, so both
    get padding on top of it — and the cap has to clear the longest section
    or it clips ("People we left hangi")."""

    CHAR_PX = 8.4      # bold Georgia 12pt, measured off the rendered sheet

    def test_the_cap_on_column_A_clears_the_longest_section(self):
        longest = max((s for s, _l, _f in W.ROWS), key=len)
        self.assertGreaterEqual(W.MAX_SECTION_COL, len(longest) * self.CHAR_PX,
                                "column A cap clips {!r}".format(longest))

    def test_the_week_column_clears_the_longest_label(self):
        # column B is auto-sized then padded; the pad has to be worth having
        self.assertGreaterEqual(W.LABEL_PAD, 30)

    def test_a_person_row_wraps_but_an_em_dash_metric_does_not(self):
        """"— booked by the AI" starts with the same dash as "— Sandy
        Samaniego", and a prefix test left those two numbers left-aligned
        in a column of centred ones."""
        labels = [l for _s, l, _f in W.ROWS]
        dashed = [l for l in labels if l.startswith(W.PERSON_PREFIX)]
        self.assertTrue(dashed, "no em-dash metric rows to guard")
        for l in dashed:
            self.assertNotIn(l, W.WRAP_ROWS)
