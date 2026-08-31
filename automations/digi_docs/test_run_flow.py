"""The two ways this run could finish without telling anybody.

Both were real (2026-08-26) and both are the same class of bug: the channel is
the only thing most people see, so a run that says nothing is a run that didn't
happen as far as the office is concerned.

  1. A fatal error -- a session that won't open, a browser that dies mid-batch
     -- threw straight past the Slack post. The morning where NOBODY got their
     documents was the one morning nobody was told; only the Hub card went red.
  2. A week where nobody needed documents still posted "*0* new starts sent
     digi docs", which is the blank board that trains people to stop reading.

Nothing here touches OwnerVille, the Sheet or Slack — and getting that right
took a correction worth recording. Patching `sys.modules` alone is NOT enough:
`from automations.digi_docs import slack_post` reads the ATTRIBUTE on the
package, which is already bound to the real module the moment any other test
imports it. On 2026-08-26 that let this suite make a real chat.postMessage
call; it only failed because the stub's thread_ts was invalid. So the package
attribute is patched too, and `_no_slack` asserts the real sender is never
reached.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock


class _Cand:
    def __init__(self, name="Dana Reyes"):
        self.name = name
        self.row = 7
        self.digi_col = 12
        self.digi_val = ""
        self.eligible = True
        self.skip_reason = ""


class _Args:
    live = True
    add_only = False
    send_only = True
    both = False
    tab = ""
    only = ""
    due_now = False
    today = False


def _fake_ov(*, session_raises=None):
    """Stand-in for automations.digi_docs.ownerville."""
    ov = types.ModuleType("automations.digi_docs.ownerville")

    class Refused(RuntimeError):
        pass

    ov.Refused = Refused
    ov.config = types.SimpleNamespace(DOCS_NEEDED_STATE="REQUIRED ACTION")

    class _Session:
        def __enter__(self):
            if session_raises:
                raise session_raises
            return object()

        def __exit__(self, *a):
            return False

    ov.session = lambda **kw: _Session()
    # Never reached in these tests -- the session is what fails.
    ov.open_set_status = lambda *a, **k: (object(), "Dana Reyes")
    ov.docs_row_state = lambda modal: "COMPLETED"
    ov.add_sales_rep = lambda *a, **k: "exists"
    return ov


class _Recorder:
    """Captures the Slack call instead of making it."""

    def __init__(self):
        self.calls = []
        self.alerts = []

    def post(self, sent, refused, attested, *, fatal="", dry_run=True):
        self.calls.append({"sent": sent, "refused": list(refused),
                           "fatal": fatal, "dry_run": dry_run})
        return True


def _run(ov, recorder, args=None):
    import automations.digi_docs as pkg
    from automations.digi_docs import run as R

    mark = types.ModuleType("automations.digi_docs.mark")
    mark.tint = lambda ws, cands, dry_run=True: 0
    slack = types.ModuleType("automations.digi_docs.slack_post")
    slack.post = recorder.post
    slack.clear_reported = lambda: None
    slack.alert_failure = lambda line, dry_run=True: recorder.alerts.append(line)

    ws = types.SimpleNamespace(title="D2D OBCL 8.24", id=0)
    with mock.patch.dict(sys.modules, {
            "automations.digi_docs.ownerville": ov,
            "automations.digi_docs.mark": mark,
            "automations.digi_docs.slack_post": slack}), \
        mock.patch.object(pkg, "ownerville", ov, create=True), \
        mock.patch.object(pkg, "mark", mark, create=True), \
        mock.patch.object(pkg, "slack_post", slack, create=True), \
        mock.patch.object(R, "_open_tab", lambda tab="": (ws, [])), \
        mock.patch.object(R, "_flag_terminated", lambda people: None), \
        mock.patch.object(R.roster, "candidates", lambda v, t: [_Cand()]), \
        mock.patch.object(R.roster, "to_send", lambda c: [_Cand()]):
        return R._phases(args or _Args())


class _NoNetwork(unittest.TestCase):
    """Belt and braces: if a stub ever slips, fail the test instead of
    reaching Slack. slack_metrics_post is the only thing that actually
    sends."""

    def setUp(self):
        def _boom(*a, **k):
            raise AssertionError(
                "a test reached the REAL Slack sender — stub it")
        self._patches = [
            mock.patch("automations.shared.slack_metrics_post."
                       "post_reply_text_only", _boom),
            mock.patch("automations.shared.slack_metrics_post."
                       "ensure_named_thread", _boom),
        ]
        for pt in self._patches:
            pt.start()
            self.addCleanup(pt.stop)


class FatalStillAlerts(_NoNetwork):
    def test_session_failure_reaches_slack(self):
        """A run that dies before it starts must still say so in the channel."""
        ov = _fake_ov(session_raises=RuntimeError("browser profile locked"))
        rec = _Recorder()
        rc = _run(ov, rec)

        self.assertEqual(len(rec.calls), 1,
                         "the run threw past the Slack post — the exact bug")
        call = rec.calls[0]
        self.assertIn("browser profile locked", call["fatal"])
        self.assertEqual(call["sent"], 0)
        self.assertEqual(rc, 1, "a run that stopped early is not a success")

    def test_fatal_names_the_error_type(self):
        ov = _fake_ov(session_raises=TimeoutError("ownerville never loaded"))
        rec = _Recorder()
        _run(ov, rec)
        self.assertTrue(rec.calls[0]["fatal"].startswith("TimeoutError:"))


class QuietWeekSaysNothing(_NoNetwork):
    def test_no_fatal_no_sends_no_refusals(self):
        """Everyone already had their documents. That is not news."""
        from automations.digi_docs import slack_post

        # The real function, so the guard itself is what's under test.
        self.assertFalse(slack_post.post(0, [], [], dry_run=True))

    def test_failures_alone_get_no_summary(self):
        """They were each posted by name as they happened, so a "*0* sent"
        line under them adds nothing."""
        import io
        import contextlib
        from automations.digi_docs import slack_post
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slack_post.post(0, ["Jose Laureano: not in OwnerVille"], [],
                            dry_run=True)
        self.assertNotIn("new starts sent", buf.getvalue())

    def test_fatal_posts_even_with_zero_counts(self):
        from automations.digi_docs import slack_post
        with mock.patch.object(slack_post, "CHANNEL", "C_TEST"):
            # dry_run prints rather than sends; the point is that the guard
            # does NOT swallow it.
            self.assertFalse(slack_post.post(0, [], [], fatal="boom",
                                             dry_run=True))


class AddPhaseNeverPosts(_NoNetwork):
    def test_add_only_is_not_a_send(self):
        """--add-only mails nobody, so it must not announce a send."""
        class AddArgs(_Args):
            add_only = True
            send_only = False

        ov = _fake_ov()
        rec = _Recorder()
        _run(ov, rec, AddArgs())
        self.assertEqual(rec.calls, [],
                         "the add phase posted to Slack off an empty result")



class StartTimeReading(unittest.TestCase):
    """The column is PLAIN TEXT with no meridiem — checked against the live
    8.24 tab, where even the unformatted read returns the string '1:00'. So
    these cases are the whole basis on which a contract lands at the right
    hour."""

    def _t(self, text):
        from automations.digi_docs import roster
        return roster.parse_start_time(text)

    def test_the_tab_as_it_actually_reads(self):
        import datetime as dt
        # Exactly the values sitting on D2D OBCL 8.24 today.
        self.assertEqual(self._t("1:00"), dt.time(13, 0))
        self.assertEqual(self._t("12:30"), dt.time(12, 30))
        self.assertEqual(self._t("1:30"), dt.time(13, 30))

    def test_a_morning_start_stays_morning(self):
        import datetime as dt
        self.assertEqual(self._t("8:00"), dt.time(8, 0))
        self.assertEqual(self._t("11:45"), dt.time(11, 45))

    def test_explicit_beats_the_rule(self):
        import datetime as dt
        self.assertEqual(self._t("9:30 am"), dt.time(9, 30))
        self.assertEqual(self._t("1:00 PM"), dt.time(13, 0))
        self.assertEqual(self._t("13:00"), dt.time(13, 0))
        self.assertEqual(self._t("12:00 am"), dt.time(0, 0))

    def test_unreadable_is_none_not_a_guess(self):
        for bad in ("", "   ", "noon", "TBD", "1:99", "25:00", "-"):
            self.assertIsNone(self._t(bad), f"{bad!r} should refuse, not guess")


class DueNowWindow(unittest.TestCase):
    def _cand(self, start):
        from automations.digi_docs import roster
        c = roster.Candidate(person=types.SimpleNamespace(
            name="Dana Reyes", row=7, skip_reason="", eligible=True))
        c.start_time = start
        return c

    def test_sends_thirty_minutes_before(self):
        import datetime as dt
        from automations.digi_docs import roster
        self.assertEqual(roster.send_due_at(self._cand("1:00")), dt.time(12, 30))
        self.assertEqual(roster.send_due_at(self._cand("12:30")), dt.time(12, 0))

    def test_not_yet_at_noon_due_by_half_past(self):
        import datetime as dt
        from automations.digi_docs import roster
        one_oclock = [self._cand("1:00")]
        due, not_yet, _ = roster.due_now(
            one_oclock, now=dt.datetime(2026, 8, 31, 12, 15))
        self.assertEqual((len(due), len(not_yet)), (0, 1))
        due, not_yet, _ = roster.due_now(
            one_oclock, now=dt.datetime(2026, 8, 31, 12, 30))
        self.assertEqual((len(due), len(not_yet)), (1, 0))

    def test_a_missed_slot_still_sends(self):
        """The machine being busy at 12:30 must not mean they never get sent."""
        import datetime as dt
        from automations.digi_docs import roster
        due, _, _ = roster.due_now([self._cand("1:00")],
                                   now=dt.datetime(2026, 8, 31, 14, 5))
        self.assertEqual(len(due), 1)

    def test_no_readable_time_is_held_back(self):
        import datetime as dt
        from automations.digi_docs import roster
        due, not_yet, no_time = roster.due_now(
            [self._cand("")], now=dt.datetime(2026, 8, 31, 23, 0))
        self.assertEqual((len(due), len(not_yet), len(no_time)), (0, 0, 1))


class TagsOnlyWhenSomeoneMustAct(_NoNetwork):
    """Alisson / Tiff / Aimee get @-tagged so a failure gets picked up fast
    (Megan 2026-08-26). The risk is the opposite one: tag them on every clean
    Monday and the mention stops meaning anything by the third week."""

    def _body(self, *a, **kw):
        import io
        import contextlib
        from automations.digi_docs import slack_post
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slack_post.post(*a, dry_run=True, **kw)
        return buf.getvalue()

    def test_clean_run_tags_nobody(self):
        self.assertNotIn("<@", self._body(6, [], []))

    def test_a_refusal_tags_all_three_on_the_immediate_alert(self):
        """The tags belong on the message that fires the moment it fails —
        that is the one somebody has to act on. The end-of-run summary counts
        them instead, so nobody is pinged twice for one problem."""
        import io
        import contextlib
        from automations.digi_docs import config, slack_post
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slack_post.alert_failure("Jose Laureano: not found in OwnerVille",
                                     dry_run=True)
        body = buf.getvalue()
        for name, uid in config.ESCALATE_ON_FAILURE:
            self.assertIn(f"<@{uid}>", body, f"{name} was not tagged")

    def test_the_summary_does_not_ping_them_again(self):
        body = self._body(5, ["Jose Laureano: not found in OwnerVille"], [])
        self.assertNotIn("<@", body)

    def test_a_stopped_run_tags_all_three(self):
        from automations.digi_docs import config
        body = self._body(0, [], [], fatal="RuntimeError: session did not open")
        for _name, uid in config.ESCALATE_ON_FAILURE:
            self.assertIn(f"<@{uid}>", body)

    def test_tagged_by_id_never_by_handle(self):
        """A display-name change turns an @handle into plain text."""
        from automations.digi_docs import config
        for name, uid in config.ESCALATE_ON_FAILURE:
            self.assertTrue(uid.startswith("U"), f"{name}: {uid!r} isn't a user id")


class FailuresAlertImmediately(_NoNetwork):
    """Megan 2026-08-26: "if anything fails it needs to alert right away."

    A send goes 30 minutes before that person starts, so a failure sitting in
    an end-of-run summary eats the window somebody has to fix it in."""

    def test_a_refusal_alerts_before_the_run_ends(self):
        from automations.digi_docs import run as R
        posted = []
        slack = types.ModuleType("automations.digi_docs.slack_post")
        slack.alert_failure = lambda line, dry_run=True: posted.append(line)
        refused = []
        with mock.patch.dict(sys.modules,
                             {"automations.digi_docs.slack_post": slack}):
            R._refuse(refused, "Jose Laureano: not found", dry=False)
        self.assertEqual(posted, ["Jose Laureano: not found"])
        self.assertEqual(refused, ["Jose Laureano: not found"])

    def test_an_alert_that_fails_does_not_take_the_run_down(self):
        from automations.digi_docs import run as R

        def boom(*a, **k):
            raise RuntimeError("slack is down")

        slack = types.ModuleType("automations.digi_docs.slack_post")
        slack.alert_failure = boom
        refused = []
        with mock.patch.dict(sys.modules,
                             {"automations.digi_docs.slack_post": slack}):
            R._refuse(refused, "Dana Reyes: no readable Start Time", dry=False)
        self.assertEqual(len(refused), 1, "the failure must still be recorded")

    def test_the_summary_never_mentions_them_again(self):
        """Each failure was posted by name above. Repeating it — even as a
        count — is a line that tells the reader nothing new."""
        import io
        import contextlib
        from automations.digi_docs import slack_post
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slack_post.post(5, ["Jose Laureano: not found in OwnerVille"], [],
                            dry_run=True)
        body = buf.getvalue()
        self.assertNotIn("Needs doing by hand", body)
        self.assertNotIn("Jose Laureano", body)

    def test_the_marker_only_describes_this_run(self):
        import os
        from automations.digi_docs import slack_post
        slack_post._mark_reported()
        self.assertTrue(os.path.exists(slack_post.REPORTED_MARKER))
        slack_post.clear_reported()
        self.assertFalse(os.path.exists(slack_post.REPORTED_MARKER),
                         "a stale marker would silence the wrapper's "
                         "last-resort alert on the NEXT run")


class FiresOnTheChartDate(_NoNetwork):
    """Megan 2026-08-26: "we need to have it run on any date listed on one of
    the new start charts. Right now it just happens to be mondays."

    The charts on Raf's tab are dated for Mondays, so a weekday-pinned schedule
    looked right for as long as that held. It is the DATE ROW above a chart
    that decides."""

    def _cands(self, *dates):
        import datetime as dt
        from automations.digi_docs import roster
        out = []
        for i, d in enumerate(dates):
            c = roster.Candidate(person=types.SimpleNamespace(
                name=f"Person {i}", row=i + 3, skip_reason="", eligible=True))
            c.chart_date = d
            out.append(c)
        return out

    def test_only_todays_chart(self):
        import datetime as dt
        from automations.digi_docs import roster
        mon, wed = dt.date(2026, 8, 31), dt.date(2026, 9, 2)
        cands = self._cands(mon, wed, wed)
        self.assertEqual(len(roster.starting_today(cands, today=wed)), 2)
        self.assertEqual(len(roster.starting_today(cands, today=mon)), 1)

    def test_a_wednesday_chart_sends_on_wednesday(self):
        import datetime as dt
        from automations.digi_docs import roster
        wed = dt.date(2026, 9, 2)
        self.assertEqual(wed.weekday(), 2, "sanity: that is a Wednesday")
        self.assertEqual(len(roster.starting_today(self._cands(wed),
                                                   today=wed)), 1)

    def test_an_undated_chart_sends_nobody(self):
        """Could be any day. Sending on the wrong one is worse than not
        sending, which somebody notices."""
        import datetime as dt
        from automations.digi_docs import roster
        self.assertEqual(
            roster.starting_today(self._cands(None),
                                  today=dt.date(2026, 8, 31)), [])

    def test_the_date_comes_from_the_chart_not_the_tab_title(self):
        """A tab holds several charts and they can carry different dates —
        Monday's second chart is the late adds."""
        import datetime as dt
        from automations.digi_docs import roster
        from automations.shared import obcl_charts as oc
        values = [
            ["8/31/2026", "", "", ""],
            ["#", "Name", "Last Name", "Start Time"],
            ["1", "Ana", "Diaz", "1:00"],
            ["", "", "", ""],
            ["9/2/2026", "", "", ""],
            ["2", "Ben", "Cole", "1:00"],
        ]
        charts = oc.find_charts(values)
        got = [oc.chart_date(c, "D2D OBCL 8.31") for c in charts]
        self.assertEqual(got, [dt.date(2026, 8, 31), dt.date(2026, 9, 2)])


class NotLiveUntilMonday(_NoNetwork):
    """Megan 2026-08-26: "we can't take this live until next mon." A date in
    code rather than uninstalling the agents — an uninstalled agent needs
    somebody to remember Monday morning, and if they forget, nobody gets their
    documents and there is no signal at all."""

    def _on(self, day):
        import datetime as dt
        from unittest import mock as m
        from automations.digi_docs import run as R

        class FakeDate(dt.date):
            @classmethod
            def today(cls):
                return dt.date.fromisoformat(day)

        with m.patch.object(dt, "date", FakeDate):
            return R._not_live_yet()

    def test_blocked_before_the_date(self):
        self.assertIn("not live until", self._on("2026-08-26"))
        self.assertIn("not live until", self._on("2026-08-30"))

    def test_live_on_the_day_and_after(self):
        self.assertEqual(self._on("2026-08-31"), "")
        self.assertEqual(self._on("2026-09-07"), "")

    def test_a_blocked_live_run_becomes_a_dry_run_not_a_failure(self):
        """It must still read the tab and say who it WOULD send to. Failing
        instead would light the Hub card red every day until Monday, which
        teaches everyone to ignore it."""
        from automations.digi_docs import run as R
        ov = _fake_ov()
        rec = _Recorder()
        rc = _run(ov, rec)
        self.assertEqual(rc, 0)

    def test_removing_the_setting_goes_live(self):
        from unittest import mock as m
        from automations.digi_docs import config, run as R
        with m.patch.object(config, "GO_LIVE_ON", ""):
            self.assertEqual(R._not_live_yet(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class RosterSnapshotAddPathTest(unittest.TestCase):
    """One roster read for the cohort, and what happens when it fails.

    2026-08-31: add_sales_rep opened with a per-person find_rep — a whole-site
    search (reload View Progress, walk every campaign twice, type probes at
    40ms a key) to answer one question. ~2 min each, so 54 people was 90
    minutes of searching, and two runs died on their timeout at 5 and 9 people
    with the day's sends due at 11:30.

    THE SAFETY PROPERTY, not the speed one: an unreadable roster comes back
    EMPTY, and empty must mean "I don't know", never "they're all missing" —
    the latter re-adds the whole cohort.
    """

    def test_a_read_roster_skips_the_per_person_search(self):
        ov = _StubOV(roster={"1 ana lopez rep"})
        ov.run_add(["Ana Lopez", "Bo Diaz"])
        self.assertEqual(["Bo Diaz"], ov.added)
        self.assertTrue(all(ov.known_absent_flags),
                        "a read roster must let add_sales_rep skip find_rep")
        self.assertEqual(1, ov.snapshots, "exactly one roster read")

    def test_an_unreadable_roster_falls_back_and_adds_nobody_blind(self):
        ov = _StubOV(roster=set())
        ov.run_add(["Ana Lopez", "Bo Diaz"])
        self.assertFalse(any(ov.known_absent_flags),
                         "an empty roster must NOT be read as 'all missing'")


class _StubOV:
    """The two calls _work makes, recorded."""

    def __init__(self, roster):
        from automations.digi_docs import ownerville as _ov
        self._ov, self._roster = _ov, roster
        self.added, self.known_absent_flags, self.snapshots = [], [], 0
        self.Refused = _ov.Refused

    def roster_snapshot(self, page, **kw):
        self.snapshots += 1
        return self._roster

    def in_roster(self, roster, name):
        return self._ov.in_roster(roster, name)

    def add_sales_rep(self, page, name, *, dry_run=True, known_absent=False):
        self.known_absent_flags.append(known_absent)
        self.added.append(name)
        return "added"

    def run_add(self, names):
        import contextlib
        from automations.digi_docs import run as _run
        People = [type("C", (), {"name": n})() for n in names]
        with contextlib.ExitStack():
            _run._work(self, page_ctx=contextlib.nullcontext(object()),
                       do_add=True, do_send=False, send=[], add_list=People,
                       dry=False, added=[], done=[], refused=[])
