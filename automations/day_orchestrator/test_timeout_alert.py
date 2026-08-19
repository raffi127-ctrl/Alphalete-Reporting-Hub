"""The real-time alert for a report KILLED at its timeout (`_alert_timeout_kill`).

WHY IT'S TESTED (2026-08-19). tableau_screenshots was killed at 30 minutes twice
that morning and #claudecorrections-and-requests never said a word: a retryable
kill only sets STILL_TRYING, and the terminal failure alert fires much later, so
a report burning its retries on 30-minute hangs was invisible until a human
noticed the Country Trackers had reached no channel at all.

What has to stay true:
  • ONE alert per report per day, however many times it is killed;
  • it files under the SAME `failure-<report_id>` incident key the terminal alert
    uses, so kill + failure + fix live in one thread;
  • the HEADLINE goes in `title` — incident_thread re-badges line one on
    resolve, so an empty title stamps ✅ onto a blank line;
  • a browser report's alert names the orphan-Chrome check, since that is what
    the kill usually means;
  • an alert that blows up never sinks the batch it is describing.

    python -m unittest automations.day_orchestrator.test_timeout_alert
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.day_orchestrator import notify
from automations.day_orchestrator import run as R
from automations.day_orchestrator import state

TARGET = dt.date(2026, 8, 19)


class _Report:
    def __init__(self, report_id, source_type="tableau", display_name=None):
        self.report_id = report_id
        self.source_type = source_type
        self.display_name = display_name or report_id


class TimeoutAlert(unittest.TestCase):
    def setUp(self):
        # state.save writes output/day_state/<date>.json — nothing to do with
        # what's being tested, and a test must not touch the real day file.
        self.saved = mock.patch.object(state, "save", lambda ds: None)
        self.saved.start()
        self.addCleanup(self.saved.stop)
        self.posts = []

        def _post_alert(title, body, **kw):
            self.posts.append({"title": title, "body": list(body), **kw})
            return "1.0000"

        self.alert = mock.patch.object(notify, "post_alert", _post_alert)
        self.alert.start()
        self.addCleanup(self.alert.stop)

    def _fire(self, r, *, attempts=1, detail="timed out after 30m",
              simulate=False):
        ds = state.DayState(date=TARGET.isoformat())
        rs = state.ReportState(report_id=r.report_id, attempts=attempts)
        ds.reports[r.report_id] = rs
        R._alert_timeout_kill(ds, r, rs, detail, TARGET,
                              dry_run=False, simulate=simulate)
        return ds

    # ---- the post itself -------------------------------------------------
    def test_headline_is_the_title_not_the_body(self):
        self._fire(_Report("tableau_screenshots",
                           display_name="Tableau Country Trackers"))
        post = self.posts[0]
        self.assertTrue(post["title"].startswith(":x:"), post["title"])
        self.assertIn("Tableau Country Trackers", post["title"])
        self.assertIn("timeout", post["title"].lower())
        # An empty/blank first line is the bug this guards: resolve() re-badges
        # line one of the parent.
        self.assertTrue(post["title"].strip())

    def test_files_under_the_reports_failure_incident(self):
        self._fire(_Report("tableau_screenshots"))
        self.assertEqual(self.posts[0]["incident"], "failure-tableau_screenshots")

    def test_body_names_the_error_the_log_and_the_rerun(self):
        self._fire(_Report("tableau_screenshots"), detail="timed out after 45m")
        body = "\n".join(self.posts[0]["body"])
        self.assertIn("timed out after 45m", body)
        self.assertIn("lucy logtail orch-2026-08-19-tableau_screenshots", body)
        self.assertIn("lucy rerun tableau_screenshots", body)

    def test_browser_reports_get_the_orphan_chrome_check(self):
        self._fire(_Report("tableau_screenshots", source_type="tableau"))
        self.assertIn("chrome_unstick", "\n".join(self.posts[0]["body"]))

    def test_non_browser_reports_do_not(self):
        self._fire(_Report("financial_pull", source_type="api"))
        self.assertNotIn("chrome_unstick", "\n".join(self.posts[0]["body"]))

    def test_says_whether_a_retry_is_coming(self):
        self._fire(_Report("tableau_screenshots"), attempts=1)
        self.assertIn("retry", "\n".join(self.posts[0]["body"]).lower())
        self.posts.clear()
        self._fire(_Report("tableau_screenshots"), attempts=R.MAX_RUN_RETRIES)
        self.assertIn("exhausted", "\n".join(self.posts[0]["body"]).lower())

    # ---- how often it fires ----------------------------------------------
    def test_once_per_report_per_day(self):
        r = _Report("tableau_screenshots")
        ds = state.DayState(date=TARGET.isoformat())
        rs = state.ReportState(report_id=r.report_id, attempts=1)
        ds.reports[r.report_id] = rs
        for _ in range(3):
            R._alert_timeout_kill(ds, r, rs, "timed out after 30m", TARGET,
                                  dry_run=False, simulate=False)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(ds.timeout_alerts_sent, ["tableau_screenshots"])

    def test_two_reports_each_get_one(self):
        ds = state.DayState(date=TARGET.isoformat())
        for rid in ("tableau_screenshots", "daily_rep_breakdown"):
            r = _Report(rid)
            rs = state.ReportState(report_id=rid, attempts=1)
            ds.reports[rid] = rs
            R._alert_timeout_kill(ds, r, rs, "timed out after 30m", TARGET,
                                  dry_run=False, simulate=False)
        self.assertEqual(len(self.posts), 2)

    def test_simulate_posts_nothing(self):
        self._fire(_Report("tableau_screenshots"), simulate=True)
        self.assertEqual(self.posts, [])

    # ---- it can never sink the batch -------------------------------------
    def test_a_broken_alert_does_not_raise(self):
        with mock.patch.object(notify, "post_alert",
                               side_effect=RuntimeError("slack down")):
            ds = self._fire(_Report("tableau_screenshots"))
        # Still marked as spoken for, so a broken Slack can't turn one kill into
        # an alert attempt per attempt.
        self.assertEqual(ds.timeout_alerts_sent, ["tableau_screenshots"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
