"""A report the CONFIG says runs today is expected even with no history that day.

Regression cover for 2026-11-17..22. Blue Ink New Start Docs moved from a
Monday agent to a daily one on 11/16 (`standalone_weekdays` [0..6],
`not_before` 07:30), the daily agent was never installed on Lucy 2, and nothing
ran for six days -- with no alert, because `_historical_expected` only expects a
report on a weekday the Activity log has SEEN it run, and Tuesday to Sunday had
none. It surfaced on Monday 11/23, off the old Monday rows.

    python -m unittest automations.machine_digest.test_declared_expected
"""
import datetime as dt
import unittest
from unittest import mock

from automations.machine_digest import run as md


class _Cfg:
    def __init__(self, reports):
        self.raw = {"reports": reports}


TUE = dt.date(2026, 11, 17)
WED = dt.date(2026, 11, 18)

BLUEINK = {"blueink_docs": {
    "on_scheduler": False, "machine": "Lucy 2",
    "display_name": "Blue Ink New Start Docs",
    "standalone_weekdays": [0, 1, 2, 3, 4, 5, 6],
    "cadence": {"weekdays": [], "not_before": "07:30"}}}


def _row(cid, started, user="Mini (auto)", machine="Mac.attlocal.net [Lucy 2]"):
    return {"Report ID": cid, "Report Name": cid, "Started At": started,
            "User": user, "Machine": machine, "Status": "success"}


# The Monday agent's last run -- the only row it ever wrote that week.
MONDAY_ROW = [_row("blueink-docs", "2026-11-16T07:30:05")]


class DeclaredExpected(unittest.TestCase):
    def test_the_blue_ink_week_is_caught_on_day_one(self):
        cfg = _Cfg(BLUEINK)
        # History alone is blind on Tuesday: it has never seen a Tuesday run.
        self.assertNotIn("blueink-docs", md._historical_expected(MONDAY_ROW, TUE))
        got = md._declared_expected(cfg, MONDAY_ROW, TUE)
        self.assertIn("blueink-docs", got)
        self.assertEqual(got["blueink-docs"]["start_hour"], 7)
        self.assertEqual(got["blueink-docs"]["machine"], "Lucy 2")
        self.assertEqual(got["blueink-docs"]["name"], "Blue Ink New Start Docs")
        self.assertIn("blueink_docs", got["blueink-docs"]["aliases"])

    def test_not_a_declared_day_is_not_expected(self):
        cfg = _Cfg({"vantura_payroll": {
            "on_scheduler": False, "standalone_weekdays": [2],
            "cadence": {"not_before": "11:00"}}})
        rows = [_row("vantura-payroll", "2026-11-11T11:00:00")]
        self.assertEqual(md._declared_expected(cfg, rows, TUE), {})
        self.assertIn("vantura-payroll", md._declared_expected(cfg, rows, WED))

    def test_no_declared_hour_means_no_deadline(self):
        rep = dict(BLUEINK["blueink_docs"], cadence={"weekdays": []})
        self.assertEqual(md._declared_expected(_Cfg({"blueink_docs": rep}),
                                               MONDAY_ROW, TUE), {})

    def test_a_report_that_never_writes_rows_is_not_expected(self):
        # vantura_week_roll's wrapper never publishes: 0 rows in 30 days, so a
        # missing row on a GOOD day looks exactly like one on a bad day.
        cfg = _Cfg({"vantura_week_roll": {
            "on_scheduler": False, "standalone_weekdays": [0],
            "cadence": {"not_before": "11:30"}}})
        self.assertEqual(md._declared_expected(cfg, [], dt.date(2026, 11, 23)), {})

    def test_only_hand_runs_are_not_proof(self):
        rows = [_row("blueink-docs", "2026-11-16T10:00:00",
                     user="Megan (hand-run)")]
        self.assertEqual(md._declared_expected(_Cfg(BLUEINK), rows, TUE), {})

    def test_proof_older_than_the_window_does_not_count(self):
        rows = [_row("blueink-docs", "2026-10-01T07:30:00")]
        self.assertEqual(md._declared_expected(_Cfg(BLUEINK), rows, TUE), {})

    def test_orchestrator_reports_are_left_to_the_orchestrator(self):
        rep = dict(BLUEINK["blueink_docs"], on_scheduler=True)
        self.assertEqual(md._declared_expected(_Cfg({"blueink_docs": rep}),
                                               MONDAY_ROW, TUE), {})

    def test_declared_start_hour_beats_not_before(self):
        rep = dict(BLUEINK["blueink_docs"], standalone_start_hour=9)
        got = md._declared_expected(_Cfg({"blueink_docs": rep}), MONDAY_ROW, TUE)
        self.assertEqual(got["blueink-docs"]["start_hour"], 9)

    def test_month_days_and_weekdays_are_both_required(self):
        rep = dict(BLUEINK["blueink_docs"], standalone_monthdays=[1, 15])
        self.assertEqual(md._declared_expected(_Cfg({"blueink_docs": rep}),
                                               MONDAY_ROW, TUE), {})

    def test_garbage_declarations_are_ignored(self):
        cfg = _Cfg({"x": {"on_scheduler": False, "standalone_weekdays": "daily",
                          "cadence": {"not_before": "soon"}},
                    "y": None})
        self.assertEqual(md._declared_expected(cfg, MONDAY_ROW, TUE), {})


class ExpectedToday(unittest.TestCase):
    def test_declared_fills_the_gap_history_leaves(self):
        got = md._expected_today(_Cfg(BLUEINK), MONDAY_ROW, TUE)
        self.assertIn("blueink-docs", got)

    def test_history_wins_where_it_already_watches(self):
        hist = {"blueink-docs": {"start_hour": 7, "machine": "Mac", "name": "B"}}
        with mock.patch.object(md, "_historical_expected", return_value=hist):
            got = md._expected_today(_Cfg(BLUEINK), MONDAY_ROW, TUE)
        self.assertEqual(got, hist)          # untouched, no aliases added

    def test_a_broken_declared_check_keeps_the_history(self):
        hist = {"other": {"start_hour": 5, "machine": "", "name": "o"}}
        with mock.patch.object(md, "_historical_expected", return_value=hist), \
                mock.patch.object(md, "_declared_expected",
                                  side_effect=RuntimeError("bad")):
            self.assertEqual(md._expected_today(_Cfg(BLUEINK), [], TUE), hist)


if __name__ == "__main__":
    unittest.main()
