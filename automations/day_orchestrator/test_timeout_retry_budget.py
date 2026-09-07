"""A TIMEOUT kill gets fewer retries than a cheap flake (MAX_TIMEOUT_RETRIES).

WHY (2026-09-07). The retry cap treated every failure the same, and the two are
nothing alike:

  org_sales_board  errored in ~50s, retried 3x, and the THIRD ONE SUCCEEDED.
                   Cheap to retry, often works — keep it.
  daily_metrics    timed out at 45m, retried to the same cap: 05:43, 06:36,
                   08:02. Three full windows, 137 minutes, never succeeded.

daily_metrics sits at order 9, so ~30 healthy reports behind it — every office
metrics thread among them — waited hours, and Megan's "metrics and trackers by
7am" was missed by five. A run killed at its timeout has already spent its whole
window; retrying spends another. So it gets one retry, not two.

What has to stay true:
  • a TIMEOUT stops after MAX_TIMEOUT_RETRIES attempts, not MAX_RUN_RETRIES;
  • a NON-timeout flake still gets the full MAX_RUN_RETRIES (that is what
    recovered org_sales_board);
  • the timeout cap is strictly the smaller of the two, or this does nothing;
  • a non-tableau report is unaffected either way.

    python -m unittest automations.day_orchestrator.test_timeout_retry_budget
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.day_orchestrator import run as R
from automations.day_orchestrator import state

TARGET = dt.date(2026, 9, 7)
TIMEOUT = R.TIMEOUT_DETAIL + "45m"
FLAKE = "exit 1 (see the log)"


class _Report:
    def __init__(self, report_id, source_type="tableau"):
        self.report_id = report_id
        self.source_type = source_type
        self.display_name = report_id
        self.command = ["automations.%s.run" % report_id]


def _attempt(report, detail, attempts):
    """Run one _attempt_report cycle whose subprocess fails with `detail`,
    with `attempts` prior attempts already on the clock. Returns the outcome
    string ('flaked' or otherwise) and the log lines."""
    ds = state.DayState(date=TARGET.isoformat())
    rs = state.ReportState(report_id=report.report_id, attempts=attempts)
    ds.reports[report.report_id] = rs
    logs = []
    with mock.patch.object(state, "save", lambda _ds: None), \
         mock.patch.object(R, "_run_report", lambda *a, **k: (False, detail)), \
         mock.patch.object(R, "_alert_timeout_kill", lambda *a, **k: None), \
         mock.patch.object(R, "_guard_chrome", lambda *a, **k: None), \
         mock.patch.object(R, "_log", lambda m: logs.append(m)):
        out = R._attempt_report(ds, report, rs, TARGET,
                                dry_run=False, simulate=True)
    return out, "\n".join(logs)


class TheTwoCapsDiffer(unittest.TestCase):
    def test_timeout_cap_is_smaller_than_the_flake_cap(self):
        """If these are ever equalised the fix is silently gone."""
        self.assertLess(R.MAX_TIMEOUT_RETRIES, R.MAX_RUN_RETRIES)
        self.assertGreaterEqual(R.MAX_TIMEOUT_RETRIES, 2,
                                "a timeout still deserves ONE retry — a network "
                                "hiccup that clears is exactly that")


class ATimeoutStopsEarly(unittest.TestCase):
    def test_first_timeout_still_retries(self):
        out, _ = _attempt(_Report("daily_metrics"), TIMEOUT, attempts=0)
        self.assertEqual(out, "flaked")

    def test_second_timeout_goes_terminal(self):
        """This is the 08:02 attempt that cost 45 minutes and helped nobody."""
        out, logs = _attempt(_Report("daily_metrics"), TIMEOUT,
                             attempts=R.MAX_TIMEOUT_RETRIES)
        self.assertNotEqual(out, "flaked")
        self.assertIn("not retrying again", logs)

    def test_it_says_why_it_stopped(self):
        """Otherwise the next reader counts attempts against MAX_RUN_RETRIES
        and files a bug against this."""
        _, logs = _attempt(_Report("daily_metrics"), TIMEOUT,
                           attempts=R.MAX_TIMEOUT_RETRIES)
        self.assertIn("timeout costs a full window", logs)
        self.assertIn("timeout_minutes", logs)


class ACheapFlakeKeepsItsRetries(unittest.TestCase):
    """org_sales_board's third attempt succeeded on 2026-09-07 — this is the
    behaviour that recovered it, and it must not be narrowed."""

    def test_same_attempt_count_flake_retries_where_timeout_stops(self):
        """The whole fix, in one comparison: identical attempt count, and only
        the FAILURE MODE decides whether it gets another window.

        `attempts` is bumped before the cap check, so at attempts=1 the flake
        is on its 2nd (2 < 3, retry) and the timeout is on its 2nd too
        (2 < 2, stop). This is the 08:02 daily_metrics attempt that never
        happens now, next to the org_sales_board retry that still does."""
        flake, _ = _attempt(_Report("org_sales_board"), FLAKE, attempts=1)
        timeout, _ = _attempt(_Report("daily_metrics"), TIMEOUT, attempts=1)
        self.assertEqual(flake, "flaked",
                         "a cheap flake must keep the full MAX_RUN_RETRIES")
        self.assertNotEqual(timeout, "flaked",
                            "a timeout must not spend a third window")

    def test_flake_stops_at_the_flake_cap(self):
        out, _ = _attempt(_Report("org_sales_board"), FLAKE,
                          attempts=R.MAX_RUN_RETRIES)
        self.assertNotEqual(out, "flaked")


class NonTableauIsUnaffected(unittest.TestCase):
    def test_a_local_report_does_not_flake_retry_on_timeout(self):
        out, _ = _attempt(_Report("some_local", source_type="local"),
                          TIMEOUT, attempts=0)
        self.assertNotEqual(out, "flaked")


if __name__ == "__main__":
    unittest.main()
