"""The week-over-week layout: find a metric by its LABEL and a week by its
HEADER DATE, never by position. A template someone re-orders by hand must not
start writing the show rate into the pay row.

  python -m unittest automations.sms_audit.test_weekly_sheet
"""
from __future__ import annotations

import datetime as dt
import unittest

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
                "anomalies": {}, "log": None}

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
        self.assertEqual(W.tab_title("11280", names), "Texts 11280 Rafael Hidalgo")
        # Raf's other two streams are their own accounts, so their own tabs
        self.assertEqual(W.tab_title("23965", names), "Texts 23965")

    def test_the_prefix_keeps_them_clear_of_the_control_sheets_tabs(self):
        # while these live in the control sheet, a bare "11280" would sit
        # among 161 unrelated tabs and could collide with one
        self.assertTrue(W.tab_title("11280", {}).startswith(W.TAB_PREFIX + " "))


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
