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


class FaultsGoToTheFaultChannel(_NoNetwork):
    """An ERROR does not belong in an office channel (Megan 2026-09-02).

    On 2026-09-02 a crashed run posted "Digi Docs — could not send @Alisson
    Rodriguez @tiff @Aimee Garibay • the run was killed before it could report —
    exit 1, see output/logs/…" into #rafs-office-recruiting-11280, @-ing three
    people over a log file on a machine they do not have. Megan: "if something is
    an error it goes into the correct channel."

    The split, pinned here: the end-of-run SUMMARY stays in the office channel —
    "3 people still need doing by hand" is work for the people in that room —
    and only FAULTS move to #claudecorrections-and-requests, where they get
    triaged and closed. The send pass is a 5-minute tick, so a fault posting to
    the office channel is not one stray message; it is a room being trained to
    stop reading itself."""

    def test_the_two_channels_are_different(self):
        from automations.digi_docs import slack_post
        self.assertNotEqual(slack_post.ALERT_CHANNEL, slack_post.CHANNEL)
        # The corrections channel, the standing home for the day's failures.
        self.assertEqual(slack_post.ALERT_CHANNEL, "C0BK5PRG259")

    def test_a_failure_posts_to_the_alert_channel_only(self):
        from automations.digi_docs import slack_post
        sent = {}

        class _C:
            def chat_postMessage(self, channel, text):
                sent["channel"] = channel
                sent["text"] = text
                return {"ok": True}

        with mock.patch.object(slack_post, "_already_alerted",
                               return_value=False), \
             mock.patch.object(slack_post, "_mark_reported", lambda: None), \
             mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=_C()):
            ok = slack_post.alert_failure("the run was killed — exit 1",
                                          dry_run=False)
        self.assertTrue(ok)
        self.assertEqual(sent["channel"], slack_post.ALERT_CHANNEL)
        self.assertNotEqual(sent["channel"], slack_post.CHANNEL)

    def test_a_failed_alert_never_takes_down_the_run(self):
        """An alert that cannot post must not raise into the caller — the run it
        is reporting on is still trying to finish."""
        from automations.digi_docs import slack_post

        class _Boom:
            def chat_postMessage(self, channel, text):
                raise RuntimeError("slack down")

        with mock.patch.object(slack_post, "_already_alerted",
                               return_value=False), \
             mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=_Boom()):
            self.assertFalse(slack_post.alert_failure("boom", dry_run=False))


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


class EmployeeIdPickTest(unittest.TestCase):
    """When the name cannot separate two people, the id has to.

    2026-08-31: the directory held two Nathan Sanchez — different people,
    different emails, four weeks apart in start date — and the Add Sales Rep
    dropdown renders both as the identical string "Nathan Sanchez". The add
    refused, correctly, and the new start went un-added until a human said
    which record was his.

    The refusal is the safe half and must stay. This is the other half: a way
    to answer it. An id that matches nothing, or matches two, is still a
    refusal — never a quiet fall back to the ambiguous name, which is the one
    outcome that mails a contract to the wrong person.
    """

    def _picker(self, labels, values):
        class _Opt:
            def __init__(self, v): self._v = v
            def get_attribute(self, _): return self._v

        class _Opts:
            def __init__(self, labels, values):
                self._l, self._v = labels, values
            def all_inner_texts(self): return list(self._l)
            def nth(self, i): return _Opt(self._v[i])

        class _Picker:
            def __init__(self, labels, values):
                self._opts = _Opts(labels, values)
                self.picked = None
            def locator(self, _): return self._opts
            def select_option(self, **kw): self.picked = kw
        return _Picker(labels, values)

    def test_the_id_picks_the_right_twin(self):
        from automations.digi_docs import ownerville as ov
        p = self._picker(["Nathan Sanchez", "Nathan Sanchez"],
                         ["9401912", "9447431"])
        ov._select_person(p, "Nathan Sanchez", employee_id="9447431")
        self.assertEqual({"index": 1}, p.picked)

    def test_two_twins_and_no_id_is_still_a_refusal(self):
        from automations.digi_docs import ownerville as ov
        p = self._picker(["Nathan Sanchez", "Nathan Sanchez"],
                         ["9401912", "9447431"])
        with self.assertRaises(ov.Refused) as cm:
            ov._select_person(p, "Nathan Sanchez")
        self.assertIn("refusing to guess", str(cm.exception))
        self.assertIsNone(p.picked)

    def test_an_id_that_matches_nothing_refuses_rather_than_falls_back(self):
        from automations.digi_docs import ownerville as ov
        p = self._picker(["Nathan Sanchez", "Nathan Sanchez"],
                         ["9401912", "9447431"])
        with self.assertRaises(ov.Refused) as cm:
            ov._select_person(p, "Nathan Sanchez", employee_id="1234567")
        self.assertIn("not in the Add Sales Rep list", str(cm.exception))
        self.assertIsNone(p.picked)

    def test_one_match_by_name_still_works_without_an_id(self):
        from automations.digi_docs import ownerville as ov
        p = self._picker(["Ana Lopez", "Bo Diaz"], ["1", "2"])
        ov._select_person(p, "Bo Diaz")
        self.assertEqual({"label": "Bo Diaz"}, p.picked)


class AttestationFailureIsNotAFailedSendTest(_NoNetwork):
    """generate_bundle IS the send. Anything after it failing is not.

    2026-08-31: the DRUG TEST section stopped expanding, tick_attestations
    timed out, and the generic handler reported twelve people as
    "Digi Docs — could not send". All twelve had their documents: the log shows
    twelve Generate Bundle clicks and the success banner passed each time. The
    cost of that mislabelling was nearly a re-run, and reading the channel it
    was impossible to tell delivery from bookkeeping.
    """

    def _run_one(self, tick_raises):
        from automations.digi_docs import run as _run

        class _OV:
            Refused = RuntimeError
            config = type("c", (), {"DOCS_NEEDED_STATE": "REQUIRED ACTION"})

            def open_set_status(self, page, name):
                return object(), name

            def docs_row_state(self, modal):
                return "REQUIRED ACTION"

            def open_docs_portal(self, page, modal):
                return type("T", (), {"close": lambda s: None})()

            def generate_bundle(self, tab, name, dry_run=True):
                return None

            def confirm_generated(self, tab, name):
                return True

            def tick_attestations(self, page, modal, dry_run=True):
                if tick_raises:
                    raise TimeoutError("Locator.wait_for: Timeout 15000ms exceeded.")
                return ["a box"]

        import contextlib
        import automations.digi_docs as _pkg
        done, refused = [], []
        person = type("C", (), {"name": "Bianca Mendez"})()
        # _refuse does `from automations.digi_docs import slack_post`. Letting
        # that resolve for real posts a live alert naming a real person off a
        # unit test — it did, on 2026-08-31, and the message had to be deleted
        # out of the channel. Stub BOTH the sys.modules entry and the package
        # attribute, because binding the real module on the package is also
        # what broke the sibling test's patch.
        stub = types.ModuleType("automations.digi_docs.slack_post")
        stub.alert_failure = lambda line, dry_run=True: None
        with mock.patch.dict(
                sys.modules, {"automations.digi_docs.slack_post": stub}), \
             mock.patch.object(_pkg, "slack_post", stub, create=True):
            _run._work(_OV(), page_ctx=contextlib.nullcontext(object()),
                       do_add=False, do_send=True, send=[person], add_list=[],
                       dry=False, added=[], done=done, refused=refused)
        return done, refused

    def test_a_sent_bundle_is_tinted_even_when_attestations_fail(self):
        """Megan 2026-08-31: "no cells are turned green for those the digi doc
        bundle sent to". The banner confirms the bundle generated and
        generating IS the send, so the cell must say sent. A blank cell reads
        as never-sent and sends somebody hunting for a bundle already gone."""
        done, refused = self._run_one(tick_raises=True)
        self.assertEqual(1, len(done))
        self.assertEqual("Bianca Mendez", done[0][0])
        self.assertEqual([], done[0][2], "no boxes were ticked")

    def test_the_alert_says_sent_and_that_no_re_send_is_needed(self):
        _, refused = self._run_one(tick_raises=True)
        self.assertEqual(1, len(refused))
        self.assertIn("bundle SENT", refused[0])
        self.assertIn("does NOT need a re-send", refused[0])

    def test_a_clean_run_is_unchanged(self):
        done, refused = self._run_one(tick_raises=False)
        self.assertEqual([], refused)
        self.assertEqual(["a box"], done[0][2])


class UnrecognisedDocsStateIsLoudTest(_NoNetwork):
    """PENDING made people invisible. Only "finished" may be silent.

    2026-08-31: the check was "REQUIRED ACTION or skip", so any other state
    meant no send, no retry and no alert — on every run, forever. A cohort sat
    in PENDING all morning while each run walked past them without a word, and
    the only reason anyone noticed was Megan opening OwnerVille by hand.

    COMPLETED is genuinely finished and stays quiet. Everything else is
    reported, because this code cannot tell whether PENDING means "packet out,
    awaiting signature" or "started and never delivered" — and a state it
    cannot interpret is the last thing that should pass silently.
    """

    def _send_one(self, state):
        import contextlib
        import automations.digi_docs as _pkg
        from automations.digi_docs import config as _cfg, run as _run

        class _OV:
            Refused = RuntimeError
            config = _cfg

            def open_set_status(self, page, name):
                return object(), name

            def docs_row_state(self, modal):
                return state

        stub = types.ModuleType("automations.digi_docs.slack_post")
        stub.alert_failure = lambda line, dry_run=True: None
        done, refused = [], []
        person = type("C", (), {"name": "Brittany Brandon"})()
        with mock.patch.dict(
                sys.modules, {"automations.digi_docs.slack_post": stub}), \
             mock.patch.object(_pkg, "slack_post", stub, create=True):
            _run._work(_OV(), page_ctx=contextlib.nullcontext(object()),
                       do_add=False, do_send=True, send=[person], add_list=[],
                       dry=False, added=[], done=done, refused=refused)
        return refused

    def test_pending_is_treated_as_already_generated(self):
        """Megan 2026-08-31: "that more than likely means they were already
        generated" — the packet is out, waiting on a signature. It behaves that
        way too: people she sent by hand moved OUT of PENDING as their bundles
        landed. If that read is ever wrong, take PENDING out of
        config.DOCS_DONE_STATES and the send treats them as sendable again."""
        from automations.digi_docs import config
        self.assertIn("PENDING", config.DOCS_DONE_STATES)
        self.assertEqual([], self._send_one("PENDING"))

    def test_completed_stays_quiet(self):
        # noqa: kept alongside the PENDING case above
        self.assertEqual([], self._send_one("COMPLETED"))

    def test_an_unreadable_state_is_reported_too(self):
        refused = self._send_one("")
        self.assertEqual(1, len(refused))
        self.assertIn("unreadable", refused[0])

    def test_a_state_nobody_has_seen_before_is_reported(self):
        refused = self._send_one("ON HOLD")
        self.assertEqual(1, len(refused))
        self.assertIn("ON HOLD", refused[0])


class FastAddOnlyTrustsAProvenRosterTest(_NoNetwork):
    """One roster read is the speed-up; PROVING it is the safety.

    2026-08-31, in order: the add ran a whole-site search per person (~2 min
    each, two runs died on their timeout partway); the first roster read fixed
    that by reading ONE page per campaign and reporting 29 real people as
    missing; and then Megan found that adding a rep MAILS them their onboarding
    email. So a partial read is not a cosmetic bug — "absent" being wrong is a
    duplicate welcome to a real person.

    Hence: trust the roster only when it proved complete, and otherwise fall
    all the way back to asking per person.
    """

    def _add(self, roster, complete):
        import contextlib
        import automations.digi_docs as _pkg
        from automations.digi_docs import ownerville as _real, run as _run

        class _OV:
            Refused = RuntimeError
            present = staticmethod(_real.present)

            def __init__(s):
                s.asked, s.known_absent_flags = [], []

            def snapshot(s, page, **kw):
                return roster, complete

            def add_sales_rep(s, page, name, *, dry_run=True, employee_id=None,
                              known_absent=False):
                s.asked.append(name)
                s.known_absent_flags.append(known_absent)
                return "added"

        ov = _OV()
        stub = types.ModuleType("automations.digi_docs.slack_post")
        stub.alert_failure = lambda line, dry_run=True: None
        people = [type("C", (), {"name": n})()
                  for n in ("Ana Lopez", "Bo Diaz")]
        with mock.patch.dict(
                sys.modules, {"automations.digi_docs.slack_post": stub}), \
             mock.patch.object(_pkg, "slack_post", stub, create=True):
            _run._work(ov, page_ctx=contextlib.nullcontext(object()),
                       do_add=True, do_send=False, send=[], add_list=people,
                       dry=False, added=[], done=[], refused=[])
        return ov

    def test_a_proven_roster_skips_the_present_and_fast_paths_the_rest(self):
        ov = self._add({"1 ana lopez rep"}, True)
        self.assertEqual(["Bo Diaz"], ov.asked, "Ana is already there")
        self.assertTrue(all(ov.known_absent_flags))

    def test_an_incomplete_roster_is_not_trusted_at_all(self):
        """Even though Ana is in it — a read that could not prove itself must
        not decide who is absent, because absent means MAIL THEM."""
        ov = self._add({"1 ana lopez rep"}, False)
        self.assertEqual(["Ana Lopez", "Bo Diaz"], ov.asked)
        self.assertFalse(any(ov.known_absent_flags))

    def test_an_empty_roster_falls_back_rather_than_adding_everyone(self):
        ov = self._add(set(), True)
        self.assertEqual(["Ana Lopez", "Bo Diaz"], ov.asked)
        self.assertFalse(any(ov.known_absent_flags),
                         "empty means unread, never 'nobody is here'")
