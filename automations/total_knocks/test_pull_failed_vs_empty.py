"""A FAILED knocks pull must never wear the "No data available" line.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.total_knocks.test_pull_failed_vs_empty

WHAT THIS GUARDS (Megan 2026-08-25). Every knocks read path used to answer `[]`
for two completely different things: an office that genuinely logged no knocks,
and a scrape that fell over. Both then took the same branch — post
"🚪 Total Knocks — Aug N — No data available", return 0 — so a broken pull
self-certified as a quiet day: the runner's `retry_on_fail` never fired, the
failure alert never posted, and the manifest went green on a report that had
pulled nothing. Isaiah's office hid behind that line for a week (8/23).

`KnocksPullFailed` (total_knocks/pull.py) is the distinction, and 12327be wired
it through all three run paths. What was missing was anything pinning it down:
the two branches differ by one `except` clause, and the failure branch is the
one nobody sees in a normal morning, so a refactor can quietly collapse them
back together and the only symptom is a green Hub card.

The contract, in both directions:

  pull raises KnocksPullFailed  →  exit 1, post NOTHING (retry + alert own it)
  pull returns []               →  exit 0, post the no-data line (verified quiet)

Both halves matter. A guard that only checked the failure case would be
satisfied by a module that fails on every empty Sunday, which is the noise this
channel is trying to get rid of.

No browser and no Slack: the pull is stubbed at the run module's namespace and
`post_reply_text_only` is stubbed to record instead of send, so an accidental
real post is impossible even if the branch logic breaks.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.rashad_metrics import knocks_run
from automations.total_knocks import run as raf_run
from automations.total_knocks.pull import KnocksPullFailed

DAY = dt.date(2026, 8, 23)      # the Sunday Isaiah's office hid behind the line

# The two shapes a pull can come back in. `FAILED` is what a stalled grid or a
# dead Time Tracker endpoint raises; `EMPTY` is a real day with no knocks.
FAILED = KnocksPullFailed(
    "Disposition grid rendered no rows at all — not even DataTables' "
    "'No data available' placeholder — so the scrape failed rather than the "
    "day being empty.")


class _Posted:
    """Stands in for slack_metrics_post.post_reply_text_only — records the call
    and reports success, so the run takes its normal path without sending."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, text, react_emoji=None, today=None, **kw):
        self.calls.append(text)
        return {"ok": True}


class RafsBoard(unittest.TestCase):
    """automations.total_knocks.run — Raf's Local Office board."""

    def _run(self, pull_result):
        """Run with `pull_disposition_day` stubbed; returns (exit_code, posts)."""
        posted = _Posted()
        stub = (mock.Mock(side_effect=pull_result)
                if isinstance(pull_result, Exception)
                else mock.Mock(return_value=(DAY, pull_result)))
        with mock.patch.object(raf_run, "pull_disposition_day", stub), \
                mock.patch("automations.shared.slack_metrics_post."
                           "post_reply_text_only", posted):
            code = raf_run.run(DAY)
        return code, posted.calls

    def test_a_failed_pull_exits_non_zero(self):
        """Non-zero is what makes the runner retry and the alert fire."""
        code, _ = self._run(FAILED)
        self.assertEqual(code, 1)

    def test_a_failed_pull_posts_nothing_at_all(self):
        """THE BUG. A failure wearing the no-data line is indistinguishable, in
        the thread, from a real quiet day — so it must not post."""
        _, posts = self._run(FAILED)
        self.assertEqual(posts, [])

    def test_a_verified_empty_day_still_posts_the_no_data_line(self):
        """The other half: a genuinely quiet Sunday is not a failure, and its
        absence has to stay VISIBLE in the thread."""
        code, posts = self._run([])
        self.assertEqual(code, 0)
        self.assertEqual(len(posts), 1)
        self.assertIn("No data available", posts[0])

    def test_the_empty_day_never_takes_the_failure_exit(self):
        """Guards the reverse regression: 'fail on empty' would open a fresh
        incident every quiet Sunday."""
        self.assertEqual(self._run([])[0], 0)

    def test_a_plain_runtime_error_is_not_swallowed(self):
        """Only KnocksPullFailed is handled. Anything else — a bad header set, a
        missing rqst token — must still crash the report rather than be filed as
        a quiet day."""
        with self.assertRaises(RuntimeError):
            self._run(RuntimeError("Disposition table is missing expected "
                                   "column(s): Total Knocks"))


class RashadsBoard(unittest.TestCase):
    """automations.rashad_metrics.knocks_run — the per-office (#elevate-sales)
    twin. Same contract, separate code path, so it needs its own guard."""

    def _run(self, pull_result, office="Rashad Wright"):
        posted = _Posted()
        stub = (mock.Mock(side_effect=pull_result)
                if isinstance(pull_result, Exception)
                else mock.Mock(return_value=(DAY, pull_result)))
        with mock.patch.object(knocks_run, "pull_office_knocks", stub), \
                mock.patch.object(knocks_run, "EXTRA_TOTALS_OFFICES", []), \
                mock.patch("automations.shared.slack_metrics_post."
                           "post_reply_text_only", posted):
            code = knocks_run.run(DAY, office_name=office)
        return code, posted.calls

    def test_a_failed_pull_exits_non_zero(self):
        self.assertEqual(self._run(FAILED)[0], 1)

    def test_a_failed_pull_posts_nothing_at_all(self):
        self.assertEqual(self._run(FAILED)[1], [])

    def test_a_verified_empty_day_posts_both_no_data_lines(self):
        """This board posts two metrics (Total Knocks + Time Gaps), so a quiet
        day owes the thread one line each."""
        code, posts = self._run([])
        self.assertEqual(code, 0)
        self.assertEqual(len(posts), 2)
        for text in posts:
            self.assertIn("No data available", text)

    def test_an_extra_offices_failure_does_not_fail_this_office(self):
        """Chan's totals ride along for comparison only — losing them must cost
        the comparison line, never the office's own post."""
        posted = _Posted()
        pulled = [("Rashad Wright", [], None), ("Chan Park", None, FAILED)]
        with mock.patch.object(knocks_run, "EXTRA_TOTALS_OFFICES", ["Chan Park"]), \
                mock.patch.object(knocks_run, "pull_offices_knocks",
                                  mock.Mock(return_value=(DAY, pulled))), \
                mock.patch("automations.shared.slack_metrics_post."
                           "post_reply_text_only", posted):
            code = knocks_run.run(DAY, office_name="Rashad Wright")
        self.assertEqual(code, 0)          # our own pull was fine (verified empty)
        self.assertEqual(len(posted.calls), 2)

    def test_this_offices_failure_inside_a_shared_session_still_fails(self):
        """The mirror of the above: when the FIRST entry (this office) carries
        the error, it is ours and it is fatal."""
        posted = _Posted()
        pulled = [("Rashad Wright", None, FAILED), ("Chan Park", [], None)]
        with mock.patch.object(knocks_run, "EXTRA_TOTALS_OFFICES", ["Chan Park"]), \
                mock.patch.object(knocks_run, "pull_offices_knocks",
                                  mock.Mock(return_value=(DAY, pulled))), \
                mock.patch("automations.shared.slack_metrics_post."
                           "post_reply_text_only", posted):
            code = knocks_run.run(DAY, office_name="Rashad Wright")
        self.assertEqual(code, 1)
        self.assertEqual(posted.calls, [])


class TheDistinctionAtTheSource(unittest.TestCase):
    """The run paths above can only tell the two apart because the SCRAPE does.
    These pin the raise sites themselves."""

    def test_a_grid_that_never_built_raises_rather_than_returning_empty(self):
        """Zero tbody rows is NOT an empty day: DataTables renders its own
        'No data available in table' row for those. Zero rows means the grid
        never finished building."""
        from automations.total_knocks import pull as raf_pull

        page = mock.Mock()
        page.wait_for_function.side_effect = TimeoutError("Timeout 10000ms")
        idx = {raf_pull._norm(c): i for i, c in enumerate(raf_pull.SHEET_COLUMNS)}
        with self.assertRaises(KnocksPullFailed):
            raf_pull._scrape_rows(page, idx)

    def test_the_wireless_grid_follows_the_same_rule(self):
        from automations.rashad_metrics import knocks_pull as w_pull
        from automations.total_knocks import pull as raf_pull

        page = mock.Mock()
        page.wait_for_function.side_effect = TimeoutError("Timeout 10000ms")
        idx = {raf_pull._norm(c): i
               for i, c in enumerate(w_pull._WIRELESS_COLUMNS)}
        with self.assertRaises(KnocksPullFailed):
            w_pull._scrape_wireless_rows(page, idx)

    def test_a_required_time_tracker_that_errors_raises(self):
        """For a wireless/NDS office the Time Tracker is the ONLY source, so a
        non-200 there is the whole board — it has to raise."""
        from automations.total_knocks import pull as raf_pull

        page = mock.Mock()
        page.evaluate.return_value = {"status": 500, "data": [], "raw": "boom"}
        with self.assertRaises(KnocksPullFailed):
            raf_pull._fetch_time_tracker(page, "rqst", "08/23/2026",
                                         required=True, verbose=False)

    def test_an_optional_time_tracker_that_errors_only_costs_the_gaps(self):
        """Where disposition rows already exist the gaps merely decorate them,
        so a failed fetch leaves Gaps blank — the documented behaviour."""
        from automations.total_knocks import pull as raf_pull

        page = mock.Mock()
        page.evaluate.return_value = {"status": 500, "data": [], "raw": "boom"}
        self.assertEqual(
            raf_pull._fetch_time_tracker(page, "rqst", "08/23/2026",
                                         required=False, verbose=False), [])

    def test_a_clean_200_with_no_rows_is_a_quiet_day_even_when_required(self):
        """Isaiah's Sunday, exactly: 200 OK carrying zero rows is VERIFIED
        empty and must not raise, or every quiet Sunday becomes an incident."""
        from automations.total_knocks import pull as raf_pull

        page = mock.Mock()
        page.evaluate.return_value = {"status": 200, "data": []}
        self.assertEqual(
            raf_pull._fetch_time_tracker(page, "rqst", "08/23/2026",
                                         required=True, verbose=False), [])


if __name__ == "__main__":
    unittest.main()
