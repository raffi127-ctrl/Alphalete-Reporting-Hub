"""The Indeed "verify a human" alert goes to the group DM. The wedge alarm does not.

Run:  PYTHONPATH=. python3 -m unittest \
          automations.oat_processing.test_indeed_alert_dm

WHAT THIS GUARDS (Raf, 2026-09-25: "Move just the indeed needs cleared alert to
the DM" + "Remove it from the corrections channel").

TWO ALARMS SHARE ONE `_post`. `run()` is the Cloudflare session-wedge alarm and
`run_resume_check()` is Indeed's human check. Both went to
#claudecorrections-and-requests through `_channel()`, so the lazy way to move
one is to edit `_channel()` — which silently moves BOTH. That is the mistake
this file exists to catch: the wedge alarm must stay on the channel, where it
is triaged with :pending: / ✅ like every other failure.

NO HARDCODED DM ID. A Slack conversation id only resolves for a member, so an
id copied from somebody else's screen names nothing to us and Slack reports
that identically to an id that never existed. push_report burned TWO such ids
learning this and both read as a permissions bug. The DM is minted with
conversations.open, and the member list is imported from push_report so the two
alerts cannot drift onto different chats. The dead ids are listed once, below,
only so this test can refuse them.

NO ✅ IN A DM, AND THAT IS EXPECTED. Lucy Reporting's token carries 13 scopes
and `mpim:history` is not one of them (probed on Lucy 2, 2026-09-25 via
`lucy slack_whoami`). incident_thread ticks a post by READING the conversation
back, so in an MPIM `open_or_followup` and `ensure_closed` both fail and `_post`
falls through to a plain chat.postMessage. Accepted by Raf. The consequence
worth guarding: the all-clear must still SAY it is clear in plain words, or an
episode would just never close and `alerted_at` would stay set forever.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.oat_processing import session_wedge_watch as w


class _Client:
    """Records what was asked of Slack. conversations_open mints a fake MPIM."""

    def __init__(self):
        self.opened_with = None
        self.posts = []

    def conversations_open(self, users):
        self.opened_with = users
        return {"channel": {"id": "D_GROUP_FAKE"}}

    def chat_postMessage(self, channel, text, **kw):
        self.posts.append((channel, text))
        return {"ts": "1.0"}


class TheGroupDm(unittest.TestCase):
    def test_minted_not_hardcoded(self):
        c = _Client()
        self.assertEqual(w._group_dm(c), "D_GROUP_FAKE")
        self.assertIsNotNone(c.opened_with)

    def test_members_come_from_push_report(self):
        """Same chat as the hourly push report, by construction."""
        from automations.push_report.run import GROUP
        c = _Client()
        w._group_dm(c)
        self.assertEqual(c.opened_with, ",".join(GROUP))

    def test_no_dm_id_is_written_down(self):
        import pathlib
        src = pathlib.Path(w.__file__).read_text()
        for dead in ("C0C56RUNA72", "C0C4FE2TD1A", "C0BJX9LJSJD"):
            self.assertNotIn(dead, src)


class WhichAlarmGoesWhere(unittest.TestCase):
    """Drive both alarms with a stub _post and read off the destination."""

    def _capture(self):
        calls = []

        def fake_post(title, body, dry_run, **kw):
            calls.append({"title": title, "to_group": kw.get("to_group", False)})
            return True
        return calls, fake_post

    def test_indeed_alert_asks_for_the_group_dm(self):
        calls, fake_post = self._capture()
        real_post, real_assess, real_state = (
            w._post, w.assess_resume_check, w._cf_state_path)
        w._post = fake_post
        w.assess_resume_check = lambda now=None: {
            "11580": (w.CF_WALL_TICKS + 1, 0, "applicant-push-11580.log")}
        w._cf_state_path = lambda office: __import__("pathlib").Path(
            "/nonexistent/cf-state")
        try:
            w.run_resume_check(dry_run=True,
                               now=dt.datetime(2026, 9, 25, 10, 0))
        finally:
            w._post, w.assess_resume_check, w._cf_state_path = (
                real_post, real_assess, real_state)
        self.assertEqual(len(calls), 1, "expected exactly one alert")
        self.assertIn("Indeed is asking to verify a human", calls[0]["title"])
        self.assertTrue(calls[0]["to_group"],
                        "the Indeed alert must target the group DM")

    def test_exactly_one_call_site_asks_for_the_dm(self):
        """Source-level, because the behavioural version passes VACUOUSLY.

        Driving run() through a stub is not a guard: its own debounce ("wedge
        still open, alerted recently — no re-ping") suppresses the post, the
        recorded-calls list comes back empty, and a for-loop over nothing
        asserts nothing. A test that is green because it never ran the code is
        worse than no test. So assert the shape of the file instead: `to_group`
        is requested in exactly ONE place, and `_post` still defaults to the
        channel for every caller that does not ask."""
        import inspect
        import pathlib
        src = pathlib.Path(w.__file__).read_text()
        self.assertEqual(src.count("to_group=True"), 1,
                         "exactly one alert may target the DM — the Indeed one")
        self.assertIs(inspect.signature(w._post).parameters["to_group"].default,
                      False, "_post must default to the corrections channel")

    def test_the_dm_request_sits_on_the_indeed_alert(self):
        """...and that one call site is Indeed's, not the wedge alarm's."""
        import inspect
        indeed = inspect.getsource(w.run_resume_check)
        wedge = inspect.getsource(w.run)
        self.assertIn("to_group=True", indeed)
        self.assertNotIn("to_group", wedge)

    def test_wedge_alarm_still_closes_on_the_channel(self):
        """run()'s all-clear must still be looked for where run() posted."""
        import inspect
        wedge = inspect.getsource(w.run)
        self.assertIn("channel=_channel()", wedge)
        self.assertNotIn("_group_dm", wedge)

    def test_channel_helper_untouched(self):
        """_channel() still answers the corrections channel for the wedge alarm."""
        self.assertEqual(w.CHANNEL, "C0BK5PRG259")
        self.assertIn(w._channel(), (w.CHANNEL, w._channel()))


class TheAllClear(unittest.TestCase):
    def test_plain_all_clear_skips_the_incident_key(self):
        """It must not borrow the WEDGE key to say Indeed is clear."""
        c = _Client()
        import automations.shared.slack_metrics_post as smp
        real_client = smp._client
        smp._client = lambda: c
        try:
            ok = w._post_plain_to_group(":white_check_mark: *clear*",
                                        ["numbers are being read again"],
                                        dry_run=False)
        finally:
            smp._client = real_client
        self.assertTrue(ok)
        self.assertEqual(len(c.posts), 1)
        channel, text = c.posts[0]
        self.assertEqual(channel, "D_GROUP_FAKE")
        self.assertIn("clear", text)

    def test_dry_run_posts_nothing(self):
        c = _Client()
        import automations.shared.slack_metrics_post as smp
        real_client = smp._client
        smp._client = lambda: c
        try:
            w._post_plain_to_group("t", ["b"], dry_run=True)
        finally:
            smp._client = real_client
        self.assertEqual(c.posts, [])


if __name__ == "__main__":
    unittest.main()
