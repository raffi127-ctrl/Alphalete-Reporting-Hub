"""Tomorrow's interviews booked, one reply per funnel, in the Daily Update thread.

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
    DATA = {"first": {"1:00 PM": 4, "9:00 AM": 3, "10:30 AM": 2},
            "second": {"10:30 AM": 1, "2:00 PM": 3, "3:15 PM": 2},
            "totals": {"first": 9, "second": 6}}

    def test_second_rounds_on_top_with_morning_afternoon(self):
        txt = S.format_funnel(dt.date(2026, 11, 16), "Main", "11280", self.DATA)
        self.assertIn("Main (11280)", txt)
        self.assertIn("Mon 11/16", txt)
        self.assertLess(txt.index("2nd rounds: 6"), txt.index("1st rounds: 9"))
        self.assertIn("2nd rounds: 6*   (morning 1 \u00b7 afternoon 5)", txt)
        self.assertIn("1st rounds: 9*   (morning 5 \u00b7 afternoon 4)", txt)

    def test_rounds_are_separate_tables_sorted_by_clock(self):
        txt = S.format_funnel(dt.date(2026, 11, 16), "Main", "11280", self.DATA)
        second, first = txt.split("1st rounds")
        self.assertNotIn("9:00 AM", second)       # 1st-only slot stays out
        order = [first.index(t) for t in ("9:00 AM", "10:30 AM", "1:00 PM")]
        self.assertEqual(order, sorted(order))    # 10:30 AM before 1:00 PM

    def test_nothing_booked(self):
        txt = S.format_funnel(dt.date(2026, 11, 16), "El Paso", "23965", {
            "first": {}, "second": {}, "totals": {"first": 0, "second": 0}})
        self.assertIn("Nothing booked yet", txt)

    def test_zero_second_rounds_still_says_so(self):
        txt = S.format_funnel(dt.date(2026, 11, 16), "AI", "24065", {
            "first": {"9:00 AM": 2}, "second": {},
            "totals": {"first": 2, "second": 0}})
        self.assertIn("2nd rounds: 0", txt)

    def test_missing_time_counts_in_total_not_in_am_pm(self):
        txt = S.format_funnel(dt.date(2026, 11, 16), "Main", "11280", {
            "first": {}, "second": {"9:00 AM": 1, "?": 2},
            "totals": {"first": 0, "second": 3}})
        self.assertIn("2nd rounds: 3*   (morning 1 \u00b7 afternoon 0)", txt)
        self.assertIn("no time", txt)


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


def _ok(*oids):
    return {o: {"first": {"9:00 AM": 1}, "second": {"2:00 PM": 1},
                "totals": {"first": 1, "second": 1}} for o in oids}


class BookedReplies(unittest.TestCase):
    """Raf 2026-11-18: one post per funnel, in the Daily Update thread."""
    def setUp(self):
        self.state = {}
        p = [mock.patch.object(R, "_load_state", lambda: dict(self.state)),
             mock.patch.object(R, "_save_state", self.state.update),
             mock.patch.object(R, "_booked_thread",
                               return_value=("DU.1", "Daily Update thread DU.1")),
             mock.patch.object(S, "screenshot",
                               return_value={"first": 1, "second": 0})]
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        self.funnels = [o for o, _ in roster.RAF.booked_funnels]

    def test_raf_funnels_are_his_four_not_hasan_or_vincent(self):
        self.assertEqual(self.funnels, ["11280", "23965", "24065", "24226"])
        self.assertNotIn("24337", self.funnels)   # Hasan
        self.assertNotIn("24332", self.funnels)   # Vincent
        self.assertEqual(self.funnels[-1], roster.RAF.linkedin_office)

    def test_one_reply_per_funnel_then_picture_into_daily_update(self):
        with mock.patch.object(S, "read", return_value=_ok(*self.funnels)) as rd, \
                mock.patch.object(R.smp, "post_reply_text_only") as txt, \
                mock.patch.object(R.smp, "post_reply_with_image") as img:
            out = R.booked_office(roster.RAF, FRI, "DF.1", dry_run=False)
        rd.assert_called_once_with(dt.date(2026, 11, 16), self.funnels)
        self.assertEqual(txt.call_count, 4)
        heads = [c.args[0].split("\n")[0] for c in txt.call_args_list]
        for (oid, label), head in zip(roster.RAF.booked_funnels, heads):
            self.assertIn(f"{label} ({oid})", head)
        for c in txt.call_args_list + img.call_args_list:
            self.assertEqual(c.kwargs["thread_ts"], "DU.1")
        img.assert_called_once()
        self.assertNotIn("error", out)
        again = R.booked_office(roster.RAF, FRI, "DF.1", dry_run=False)
        self.assertEqual(again, {"skipped": True})

    def test_one_bad_funnel_retries_alone(self):
        data = _ok("11280", "24065", "24226")
        data["23965"] = {"error": "TimeoutError: calendar"}
        with mock.patch.object(S, "read", return_value=data), \
                mock.patch.object(R.smp, "post_reply_text_only") as txt, \
                mock.patch.object(R.smp, "post_reply_with_image"):
            out = R.booked_office(roster.RAF, FRI, "DF.1", dry_run=False)
        self.assertIn("El Paso (23965)", out["error"])
        self.assertEqual(txt.call_count, 3)
        self.assertNotIn("raf|booked|23965", self.state)
        with mock.patch.object(S, "read", return_value=_ok("23965")) as rd, \
                mock.patch.object(R.smp, "post_reply_text_only") as txt, \
                mock.patch.object(R.smp, "post_reply_with_image") as img:
            R.booked_office(roster.RAF, FRI, "DF.1", dry_run=False)
        rd.assert_called_once_with(dt.date(2026, 11, 16), ["23965"])
        txt.assert_called_once()
        img.assert_not_called()

    def test_appstream_down_is_reported_not_raised(self):
        with mock.patch.object(S, "read", side_effect=RuntimeError("login")), \
                mock.patch.object(R.smp, "post_reply_text_only") as txt, \
                mock.patch.object(R.smp, "post_reply_with_image"):
            out = R.booked_office(roster.RAF, FRI, "1", dry_run=False)
        self.assertIn("login", out["error"])
        txt.assert_not_called()
        self.assertFalse([k for k in self.state if "|booked|" in k])

    def test_dry_run_records_nothing(self):
        with mock.patch.object(S, "read", return_value=_ok(*self.funnels)), \
                mock.patch.object(R.smp, "post_reply_text_only"), \
                mock.patch.object(R.smp, "post_reply_with_image"):
            R.booked_office(roster.RAF, FRI, None, dry_run=True)
        self.assertEqual(self.state, {})

    def test_retry_tick_posts_only_whats_missing(self):
        today = R.local_now(roster.RAF).date().isoformat()
        self.state.update({"raf": today,
                           "raf|text|Admin Staff": today,
                           "raf|text|Alphalete A-Team Chat": today})
        with mock.patch.object(R, "booked_office",
                               return_value={"posted": ["11280"]}) as bk, \
                mock.patch.object(R, "text_office") as texts:
            out = R.post_office(roster.RAF, None, dry_run=False)
        texts.assert_not_called()
        bk.assert_called_once()
        self.assertEqual(out["booked"], {"posted": ["11280"]})


class BookedThread(unittest.TestCase):
    def test_daily_update_thread_wins(self):
        import automations.raf_daily_update.run as DU
        with mock.patch.object(R.smp, "_client"), \
                mock.patch.object(DU, "_existing_parent", return_value="DU.9"), \
                mock.patch.object(R.smp, "ensure_named_thread") as df:
            ts, _ = R._booked_thread(roster.RAF, FRI, "DF.1", dry_run=False)
        self.assertEqual(ts, "DU.9")
        df.assert_not_called()

    def test_no_daily_update_falls_back_to_daily_focus(self):
        import automations.raf_daily_update.run as DU
        with mock.patch.object(R.smp, "_client"), \
                mock.patch.object(DU, "_existing_parent", return_value=""):
            ts, where = R._booked_thread(roster.RAF, FRI, "DF.1", dry_run=False)
        self.assertEqual(ts, "DF.1")
        self.assertIn("Daily Focus", where)

    def test_slack_read_error_falls_back_too(self):
        import automations.raf_daily_update.run as DU
        with mock.patch.object(R.smp, "_client"), \
                mock.patch.object(DU, "_existing_parent",
                                  side_effect=RuntimeError("ratelimited")), \
                mock.patch.object(R.smp, "ensure_named_thread",
                                  return_value={"thread_ts": "DF.2"}):
            ts, _ = R._booked_thread(roster.RAF, FRI, None, dry_run=False)
        self.assertEqual(ts, "DF.2")


class LinkedInCaption(unittest.TestCase):
    def test_caption(self):
        c = S.screenshot_caption(dt.date(2026, 11, 16), {"first": 3, "second": 2})
        self.assertIn("Mon 11/16", c)
        self.assertIn("24226", c)
        self.assertLess(c.index("2nd rounds: *2*"), c.index("1st rounds: *3*"))


if __name__ == "__main__":
    unittest.main()
