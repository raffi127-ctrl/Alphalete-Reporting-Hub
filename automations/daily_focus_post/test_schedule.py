"""Tomorrow's 1st/2nd round slots reply on the 7 PM Daily Focus thread.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.daily_focus_post.test_schedule

Nothing touches AppStream, Google or Slack.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.daily_focus_post import roster, run as R, schedule as S

FRI = dt.date(2026, 11, 13)


class NextDay(unittest.TestCase):
    def test_friday_shows_monday(self):
        self.assertEqual(S.next_day(FRI), dt.date(2026, 11, 16))

    def test_weekday_shows_tomorrow(self):
        self.assertEqual(S.next_day(dt.date(2026, 11, 12)), FRI)


class Format(unittest.TestCase):
    def test_slots_sorted_by_clock_with_totals(self):
        txt = S.format_text(dt.date(2026, 11, 16), {
            "first": {"1:00 PM": 4, "9:00 AM": 3, "10:30 AM": 2},
            "second": {"10:30 AM": 1, "2:00 PM": 3},
            "totals": {"first": 9, "second": 4}})
        self.assertIn("Mon 11/16", txt)
        self.assertIn("1st rounds: *9*", txt)
        self.assertIn("2nd rounds: *4*", txt)
        order = [txt.index(t) for t in ("9:00 AM", "10:30 AM", "1:00 PM", "2:00 PM")]
        self.assertEqual(order, sorted(order))      # 10:30 AM before 1:00 PM

    def test_nothing_booked(self):
        txt = S.format_text(dt.date(2026, 11, 16), {
            "first": {}, "second": {}, "totals": {"first": 0, "second": 0}})
        self.assertIn("Nothing booked yet", txt)


class RosterTags(unittest.TestCase):
    def test_raf_tags_the_team(self):
        want = {"U045Z8N0ZQC", "U0488R0E9D5", "U05094TTPKQ", "U067WLPK92T",
                "U09MXMU76MB", "U0BBG374GE9", "U0B9924FHCL"}
        self.assertEqual(set(roster.RAF.tag_user_ids), want)
        # the look-alike accounts must never sneak in
        self.assertNotIn("U068T4LA0C8", roster.RAF.tag_user_ids)
        self.assertNotIn("U09TWLG53EZ", roster.RAF.tag_user_ids)

    def test_caption_tags_everyone(self):
        cap = R._caption(FRI, roster.RAF)
        for u in roster.RAF.tag_user_ids:
            self.assertIn(f"<@{u}>", cap)


class ScheduleReply(unittest.TestCase):
    def setUp(self):
        self.state = {}
        p = [mock.patch.object(R, "_load_state", lambda: dict(self.state)),
             mock.patch.object(R, "_save_state", self.state.update)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def test_posts_once_then_skips(self):
        data = {"first": {"9:00 AM": 1}, "second": {}, "totals": {"first": 1, "second": 0}}
        with mock.patch.object(S, "read", return_value=data) as rd, \
                mock.patch.object(R.smp, "post_reply_text_only",
                                  return_value={"ok": True}) as post:
            out = R.schedule_office(roster.RAF, FRI, "123.4", dry_run=False)
            self.assertIn("text", out)
            rd.assert_called_once_with(dt.date(2026, 11, 16),
                                       roster.RAF.schedule_offices)
            self.assertEqual(post.call_args.kwargs["thread_ts"], "123.4")
            again = R.schedule_office(roster.RAF, FRI, "123.4", dry_run=False)
            self.assertEqual(again, {"skipped": True})
            post.assert_called_once()

    def test_appstream_failure_is_reported_not_raised_and_retried(self):
        with mock.patch.object(S, "read", side_effect=RuntimeError("login")), \
                mock.patch.object(R.smp, "post_reply_text_only") as post:
            out = R.schedule_office(roster.RAF, FRI, "1", dry_run=False)
        self.assertIn("error", out)
        post.assert_not_called()
        self.assertNotIn("raf|schedule", self.state)   # next tick retries

    def test_dry_run_records_nothing(self):
        data = {"first": {}, "second": {}, "totals": {"first": 0, "second": 0}}
        with mock.patch.object(S, "read", return_value=data), \
                mock.patch.object(R.smp, "post_reply_text_only",
                                  return_value={"dry_run": True}):
            R.schedule_office(roster.RAF, FRI, None, dry_run=True)
        self.assertEqual(self.state, {})


if __name__ == "__main__":
    unittest.main()
