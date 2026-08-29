"""The AppStream re-seed alert must fire on EVIDENCE, never on a forecast.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_appstream_watch_probe

Two separate false alarms taught this file its rules. Both made the same alert
page Megan repeatedly while the 4am batch ran clean, so both are pinned here.

FALSE ALARM 1 — THE DEAD LOGIN ROUTE (fixed 2026-08-27, `e6bba32`).
`selfheal_ok()` called appstream_direct_session with force_form_login=True /
allow_form_login=True — the rcaptain login form. Hours earlier the same day,
`d793ea3` had made that form off-limits to scheduled runs (allow_form_login
defaults False, gated by _appstream_form_login_allowed), so no report had driven
it since. The watch failed a route nothing uses and posted "the self-heal is
BROKEN". The bar: probe with the SAME flags a scheduled report passes. If that
test fails because someone re-enabled the form here, check whether the reports'
own default changed first.

FALSE ALARM 2 — THE IMPOSSIBLE PREDICTION (fixed 2026-08-29).
Health was "does the stored rqst outlast the next 4am batch + 90 min?" while the
rqst TTL is a fixed ~2 HOURS. No token can pass that test, so `healthy` was
False every hour of every day and every ping window escalated to the live probe
— where any single flake (stray Chrome, busy profile, slow console) became a
page. Measured on Lucy 1 mid-batch at 05:17 on 8/29, holder re-exporting a
VERIFIED session every six minutes: token "valid 0.7h more (until Aug 29
6:01AM)" against a required Aug 30 05:30.

THE RULES THIS FILE ENFORCES, so neither can come back:
  • the probe drives the reports' reuse path, never the login form;
  • a healthy-right-now token never pages, however little time is left on it;
  • the stored token's timestamp ALONE can never page AppStream;
  • one flaky probe is not an outage — it takes two;
  • a report that actually failed on a session DOES page, the same day, in or
    out of any window. Genuine outages must stay loud.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.shared import appstream_watch as w


class _Page:
    def __init__(self, has_console: bool):
        self._has = has_console

    def locator(self, sel):
        assert sel == "#searchMC"
        return mock.Mock(count=mock.Mock(return_value=1 if self._has else 0))


class _Session:
    """Stands in for appstream_direct_session, recording how it was called."""

    def __init__(self, page=None, raises=None):
        self.page, self.raises, self.kwargs = page, raises, None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.raises:
            raise self.raises
        outer = self

        class _CM:
            def __enter__(self):
                return outer.page

            def __exit__(self, *a):
                return False

        return _CM()


def _patch(session):
    """appstream_watch imports from tableau_patchright INSIDE selfheal_ok, so the
    patch has to land on the source module, not on a watch-level name."""
    return mock.patch.dict(
        "sys.modules",
        {"automations.shared.tableau_patchright": mock.Mock(
            AppStreamBusy=_Busy, appstream_direct_session=session)},
    )


class _Busy(Exception):
    pass


# A stored AppStream session that is ALIVE but short — the normal state on any
# runner, and the one the old "must outlast tomorrow's 4am" test called stale.
LIVE_BUT_SHORT = {"ok": True,
                  "rqst_expiry": dt.datetime(2026, 8, 29, 6, 1),
                  "hours_left": 0.74, "what": "AppStream",
                  "reason": "AppStream rqst token valid 0.7h more (until Aug 29 6:01AM)"}
DEAD = {"ok": False, "rqst_expiry": None, "hours_left": None,
        "what": "AppStream", "reason": "EXPIRED"}


def _run_watch(hour, *, probe_ok=True, state=None, status=None, export_age=600.0,
               failures=None, day=(2026, 8, 27), reports=()):
    """One watch() evaluation with every side effect captured.

    `status` is the per-session dict session_status would return (the same one
    is used for both sessions unless it carries its own "what"). `failures` is
    what the day_state read finds. Patching probe_appstream_healthy rather than
    selfheal_ok keeps the retry's real sleep out of the tests."""
    sent = []
    base = dict(status or DEAD)
    with mock.patch.object(w, "_now",
                           return_value=dt.datetime(*day, hour, 0)), \
         mock.patch.object(w, "_load_state", return_value=dict(state or {})), \
         mock.patch.object(w, "_save_state") as save, \
         mock.patch.object(w, "_export_age_min", return_value=export_age), \
         mock.patch.object(w, "session_status",
                           side_effect=lambda p, what: {**base, "what": what}), \
         mock.patch.object(w, "_appstream_reports_to_rerun",
                           return_value=list(reports)), \
         mock.patch.object(w, "_enqueue_rerun") as rerun, \
         mock.patch.object(w, "appstream_session_failures",
                           return_value=list(failures or [])), \
         mock.patch.object(w, "probe_appstream_healthy",
                           return_value=(probe_ok, "why")) as probe, \
         mock.patch.object(w, "_alert", side_effect=lambda t, d: sent.append(t)):
        res = w.watch(dry_run=True)
    saved = save.call_args[0][0] if save.call_args else {}
    return sent, probe, saved, res, rerun


class ProbeUsesTheReportPath(unittest.TestCase):
    def test_never_asks_for_the_login_form(self):
        """The regression itself: no force_form_login, no allow_form_login."""
        s = _Session(page=_Page(True))
        with _patch(s):
            ok, _ = w.selfheal_ok()
        self.assertTrue(ok)
        self.assertFalse(s.kwargs.get("force_form_login", False),
                         "probe drove the login form — reports never do")
        self.assertFalse(s.kwargs.get("allow_form_login", False),
                         "probe allowed the login form — reports never do")

    def test_live_console_is_healthy(self):
        with _patch(_Session(page=_Page(True))):
            ok, why = w.selfheal_ok()
        self.assertTrue(ok)
        self.assertIn("same path as the reports", why)

    def test_no_console_is_unhealthy(self):
        with _patch(_Session(page=_Page(False))):
            ok, why = w.selfheal_ok()
        self.assertFalse(ok)
        self.assertIn("#searchMC", why)

    def test_dead_session_is_unhealthy_and_says_so(self):
        with _patch(_Session(raises=RuntimeError("no live token"))):
            ok, why = w.selfheal_ok()
        self.assertFalse(ok)
        self.assertIn("dead", why.lower())
        # It must NOT claim the login is broken — that was the false alarm.
        self.assertNotIn("self-heal is broken", why.lower())

    def test_busy_profile_counts_as_healthy(self):
        """Another report holding the session is proof the path works."""
        with _patch(_Session(raises=_Busy("profile in use"))):
            ok, why = w.selfheal_ok()
        self.assertTrue(ok)
        self.assertIn("busy", why.lower())

    def test_yields_instead_of_queueing_behind_a_report(self):
        s = _Session(page=_Page(True))
        with _patch(s):
            w.selfheal_ok()
        self.assertTrue(s.kwargs.get("yield_if_busy"),
                        "probe must step aside for a real report, not block it")


class ItDoesNotSitOnADaytimeFailureUntil6pm(unittest.TestCase):
    """THE TEN-HOUR SILENCE (Lucy 1, 2026-08-27). The holder lost its rqst token
    at 08:41 and could not re-mint. Nothing was wrong with the alert's judgement
    — a report genuinely could not open the console — but the only windows that
    could speak were 6pm and 3am, so the first anyone heard was the 6:41pm ping,
    after the working day, asking for a re-seed only a human at a keyboard can
    do. The probe is still the gate: on a normal day the stored token is expired
    at 8am too, the probe passes, and nothing is sent."""

    @staticmethod
    def _run(hour, *, probe_ok, state=None):
        sent, probe, saved, _res, _rerun = _run_watch(
            hour, probe_ok=probe_ok, state=state)
        return sent, probe, saved

    def test_a_dead_session_at_9am_pings_the_same_morning(self):
        sent, _, state = self._run(9, probe_ok=False)
        self.assertTrue(sent, "a daytime failure must not wait for 6pm")
        self.assertIn("AppStream", sent[0])
        self.assertEqual(state.get("alerted_daytime_for"), "2026-08-27")

    def test_a_healthy_session_at_9am_says_nothing(self):
        """The normal state: token expired between runs, holder fine. The probe
        is what separates this from the real thing — it must stay the gate."""
        sent, probe, _ = self._run(9, probe_ok=True)
        self.assertEqual([t for t in sent if "AppStream" in t], [])
        probe.assert_called_once()

    def test_it_pings_once_a_day_not_every_six_minutes(self):
        sent, _, _ = self._run(9, probe_ok=False,
                               state={"alerted_daytime_for": "2026-08-27"})
        self.assertEqual(sent, [])

    def test_the_6pm_ping_still_fires_for_a_session_that_died_after_hours(self):
        sent, _, state = self._run(18, probe_ok=False,
                                   state={"alerted_daytime_for": "2026-08-27"})
        self.assertTrue(sent)
        self.assertIn("4am", sent[0])
        self.assertEqual(state.get("alerted_evening_for"), "2026-08-27")

    def test_ownerville_alone_never_earns_a_daytime_ping(self):
        """Only a LIVE probe failure earns this window. Ownerville is judged by
        its stored expiry alone, and a daily unprobed 8am ping about it would be
        a brand-new false alarm — the exact thing this watch keeps getting wrong."""
        sent, _, state = self._run(9, probe_ok=True)   # appstream fine, ov "dead"
        self.assertEqual(sent, [])
        self.assertIsNone(state.get("alerted_daytime_for"))

    def test_nothing_wakes_anyone_at_2am(self):
        """Outside every window — the 3am pre-batch check owns that hour."""
        sent, probe, _ = self._run(2, probe_ok=False)
        self.assertEqual(sent, [])
        probe.assert_not_called()


class AShortButLiveTokenIsHealthy(unittest.TestCase):
    """FALSE ALARM 2. The rqst TTL is ~2h; the old test demanded it outlast the
    next 4am batch by 90 min. Nothing can pass that, so every healthy session
    read as stale and every ping window went to the probe. These are the exact
    numbers measured on Lucy 1 at 05:17 on 2026-08-29, mid-batch, with the
    holder re-exporting a VERIFIED session every six minutes."""

    def test_a_token_with_43_minutes_left_never_pages(self):
        for hour in (3, 9, 18):
            with self.subTest(hour=hour):
                sent, probe, _, res, _ = _run_watch(
                    hour, status=LIVE_BUT_SHORT, export_age=6.0,
                    day=(2026, 8, 29))
                self.assertEqual(sent, [], f"paged at {hour}:00 on a live token")
                self.assertTrue(res["healthy_now"])
                probe.assert_not_called()   # healthy: not even worth the Chrome

    def test_it_does_not_page_just_because_the_token_cannot_reach_4am(self):
        """The regression in one line: 0.7h left is fine, and must stay fine."""
        _, _, _, res, _ = _run_watch(18, status=LIVE_BUT_SHORT, export_age=6.0,
                                     day=(2026, 8, 29))
        self.assertEqual(res["stale"], [])

    def test_a_stale_export_still_counts_against_a_live_token(self):
        """The holder writes that file only when the session validates, so a
        live-looking token nobody has re-exported in 10h is the real signal the
        expiry alone would miss. Probe decides; here it fails, so it pages."""
        sent, probe, _, _, _ = _run_watch(18, status=LIVE_BUT_SHORT,
                                          export_age=600.0, probe_ok=False,
                                          day=(2026, 8, 29))
        probe.assert_called_once()
        self.assertTrue(sent)


class TheStoredTimestampAloneNeverPagesAppStream(unittest.TestCase):
    """THE INVARIANT. AppStream may only reach the alert list through a failed
    LIVE probe. Its token is expired or short more often than not, so letting a
    file's timestamp put it there is the whole cry-wolf mechanism."""

    def test_expired_token_plus_passing_probe_is_silent(self):
        sent, _, _, res, _ = _run_watch(18, status=DEAD, probe_ok=True)
        self.assertEqual([t for t in sent if "AppStream" in t], [])
        self.assertNotIn("AppStream", res["stale"])

    def test_with_probing_off_appstream_can_never_page(self):
        """--no-probe strips both evidence sources, so the only thing left is
        the timestamp — which by this rule is not grounds to wake anyone."""
        sent = []
        with mock.patch.object(w, "_now", return_value=dt.datetime(2026, 8, 27, 18, 0)), \
             mock.patch.object(w, "_load_state", return_value={}), \
             mock.patch.object(w, "_save_state"), \
             mock.patch.object(w, "_export_age_min", return_value=600.0), \
             mock.patch.object(w, "session_status",
                               side_effect=lambda p, what: {**DEAD, "what": what}), \
             mock.patch.object(w, "_appstream_reports_to_rerun", return_value=[]), \
             mock.patch.object(w, "_alert", side_effect=lambda t, d: sent.append(t)):
            res = w.watch(dry_run=True, probe=False)
        self.assertNotIn("AppStream", res["stale"])
        self.assertEqual([t for t in sent if "AppStream" in t], [])


class OneFlakyProbeIsNotAnOutage(unittest.TestCase):
    """The probe opens a real Chrome against a profile the batch also uses, so
    'profile in use' / a stray human Chrome / a slow console all land here as a
    failure. A dead session fails every time; a hiccup does not."""

    def test_a_probe_that_passes_on_the_retry_is_healthy(self):
        calls = [(False, "profile in use"), (True, "console opened")]
        with mock.patch.object(w, "selfheal_ok", side_effect=calls), \
             mock.patch.object(w.time, "sleep") as slept:
            ok, why = w.probe_appstream_healthy(attempts=2, sleep_s=0)
        self.assertTrue(ok, "one flake must not count as an outage")
        self.assertIn("recovered on attempt 2", why)
        slept.assert_called_once()

    def test_a_session_that_fails_every_time_is_an_outage(self):
        with mock.patch.object(w, "selfheal_ok",
                               return_value=(False, "stored session is dead")), \
             mock.patch.object(w.time, "sleep"):
            ok, why = w.probe_appstream_healthy(attempts=2, sleep_s=0)
        self.assertFalse(ok)
        self.assertIn("dead", why)
        self.assertIn("2x", why)

    def test_it_asks_more_than_once(self):
        with mock.patch.object(w, "selfheal_ok",
                               return_value=(False, "x")) as probe, \
             mock.patch.object(w.time, "sleep"):
            w.probe_appstream_healthy(attempts=2, sleep_s=0)
        self.assertEqual(probe.call_count, 2)


class ARealFailureStillWakesSomeone(unittest.TestCase):
    """The other half of the fix. Quieting the forecast is only safe because a
    report that ACTUALLY could not get a session now pages on its own — and,
    unlike every other path here, not held to a window. A 4am outage used to
    wait until the 8am ping to say anything."""

    FAILED = [("daily_focus", "no rqst token — re-seed it with a one-time human login")]

    def test_it_pages_the_moment_a_report_fails_on_a_session(self):
        sent, _, saved, res, _ = _run_watch(4, status=LIVE_BUT_SHORT,
                                            export_age=6.0, failures=self.FAILED)
        self.assertTrue(sent, "a real session failure must not be silent")
        self.assertIn("daily_focus", sent[0])
        self.assertIn("could not open", sent[0])
        self.assertEqual(res["failed_reports"], ["daily_focus"])
        self.assertEqual(saved.get("alerted_realfail_for"), "2026-08-27")

    def test_it_pages_outside_every_ping_window(self):
        """2am is the one hour the windows deliberately leave silent."""
        sent, _, _, _, _ = _run_watch(2, status=LIVE_BUT_SHORT, export_age=6.0,
                                      failures=self.FAILED)
        self.assertTrue(sent, "a real outage must not wait for a window")

    def test_it_carries_the_reseed_command(self):
        sent, _, _, _, _ = _run_watch(4, status=LIVE_BUT_SHORT, export_age=6.0,
                                      failures=self.FAILED)
        self.assertIn("--appstream-login", sent[0])

    def test_it_says_it_once_a_day_not_every_six_minutes(self):
        sent, _, _, _, _ = _run_watch(
            4, status=LIVE_BUT_SHORT, export_age=6.0, failures=self.FAILED,
            state={"alerted_realfail_for": "2026-08-27"})
        self.assertEqual(sent, [])

    def test_a_healthy_day_with_no_failures_says_nothing(self):
        sent, _, _, _, _ = _run_watch(4, status=LIVE_BUT_SHORT, export_age=6.0,
                                      failures=[])
        self.assertEqual(sent, [])


class ItReadsRealFailuresFromTheOrchestratorsOwnRecord(unittest.TestCase):
    """appstream_session_failures() is the ground truth the watch never used to
    consult. It must catch a session failure and ignore an ordinary report bug —
    a broad match here would be the same cry-wolf in a new costume."""

    @staticmethod
    def _failures(reports, ids=("daily_focus", "att_focus_raf"), tmp=None):
        import json
        from automations.day_orchestrator import state as day_state
        state_file = tmp / "2026-08-29.json"
        state_file.write_text(json.dumps({"reports": reports}), encoding="utf-8")
        cfg_reports = [mock.Mock(report_id=r, source_type="appstream") for r in ids]
        with mock.patch.object(w, "_now", return_value=dt.datetime(2026, 8, 29, 9, 0)), \
             mock.patch.dict("sys.modules", {}), \
             mock.patch("automations.day_orchestrator.registry.load_config",
                        return_value={}), \
             mock.patch("automations.day_orchestrator.registry.scheduled_today",
                        return_value=cfg_reports), \
             mock.patch.object(day_state, "STATE_DIR", tmp):
            return w.appstream_session_failures()

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_session_failure_is_caught(self):
        out = self._failures({"daily_focus": {
            "status": "FAILED",
            "last_reason": "AppStream session is stale — re-seed it"}}, tmp=self.tmp)
        self.assertEqual([r for r, _ in out], ["daily_focus"])

    def test_blocked_session_counts_on_its_own(self):
        out = self._failures({"daily_focus": {
            "status": "BLOCKED_SESSION", "last_reason": ""}}, tmp=self.tmp)
        self.assertEqual([r for r, _ in out], ["daily_focus"])

    def test_an_ordinary_report_bug_does_not_ask_for_a_reseed(self):
        """The guard against the new false alarm: a report that died of its own
        fault must not put a re-seed request in front of anyone."""
        out = self._failures({"daily_focus": {
            "status": "FAILED",
            "last_reason": "KeyError: 'Total Knocks' — column missing"}},
            tmp=self.tmp)
        self.assertEqual(out, [])

    def test_a_done_report_is_not_a_failure(self):
        out = self._failures({"daily_focus": {
            "status": "DONE", "last_reason": ""}}, tmp=self.tmp)
        self.assertEqual(out, [])

    def test_a_non_appstream_report_is_ignored(self):
        """Yesterday's two real failures (mobrium_list, sci_campaigns) were not
        AppStream — this alert must stay silent about reports it does not own."""
        out = self._failures(
            {"mobrium_list": {"status": "FAILED",
                              "last_reason": "could not sign in"}},
            ids=("daily_focus",), tmp=self.tmp)
        self.assertEqual(out, [])

    def test_a_broken_read_never_pages(self):
        """It is an ADDITIONAL alarm; if it cannot read, it says nothing rather
        than inventing an outage."""
        with mock.patch("automations.day_orchestrator.registry.load_config",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(w.appstream_session_failures(), [])


class RecoveryOnlyRerunsWhatActuallyFailed(unittest.TestCase):
    """CAUGHT IN PRODUCTION, 2026-08-29 05:29. The recovery list was "every
    AppStream report that isn't DONE", which silently includes PENDING — reports
    the orchestrator has not reached yet and still owns. Deploying the health fix
    flipped last_ok_appstream False→True mid-batch, read as a recovery, and
    re-queued other_office_knocks, which the day-state listed as
    `pending - daily_metrics`: waiting on a dependency. mini_control._action_rerun
    runs a report directly and does NOT check deps, so that is an early,
    dependency-violating run of a report that posts to Slack.

    A re-seed recovers what a session failure COST. It does not reach into the
    batch and start work the batch is going to do itself."""

    @staticmethod
    def _rerun_list(reports, tmp):
        import json
        from automations.day_orchestrator import state as day_state
        (tmp / "2026-08-29.json").write_text(
            json.dumps({"reports": reports}), encoding="utf-8")
        cfg = [mock.Mock(report_id=r, source_type="appstream",
                         machine="Lucy 1", order=i)
               for i, r in enumerate(("daily_metrics", "other_office_knocks"))]
        with mock.patch("automations.day_orchestrator.registry.load_config",
                        return_value={}), \
             mock.patch("automations.day_orchestrator.registry.scheduled_today",
                        return_value=cfg), \
             mock.patch.object(day_state, "STATE_DIR", tmp):
            return w._appstream_reports_to_rerun(dt.datetime(2026, 8, 29, 5, 29))

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_pending_report_is_never_rerun(self):
        """The exact production case, with its real dependency note."""
        out = self._rerun_list(
            {"other_office_knocks": {"status": "PENDING",
                                     "last_reason": "pending - daily_metrics"}},
            self.tmp)
        self.assertEqual(out, [], "re-queued a report the batch had not reached")

    def test_a_failed_report_is_rerun(self):
        out = self._rerun_list(
            {"other_office_knocks": {"status": "FAILED", "last_reason": "no rqst"}},
            self.tmp)
        self.assertEqual([r for r, _ in out], ["other_office_knocks"])

    def test_a_blocked_session_report_is_rerun(self):
        out = self._rerun_list(
            {"daily_metrics": {"status": "BLOCKED_SESSION", "last_reason": ""}},
            self.tmp)
        self.assertEqual([r for r, _ in out], ["daily_metrics"])

    def test_done_and_still_trying_are_left_alone(self):
        out = self._rerun_list(
            {"daily_metrics": {"status": "DONE", "last_reason": ""},
             "other_office_knocks": {"status": "STILL_TRYING", "last_reason": ""}},
            self.tmp)
        self.assertEqual(out, [])

    def test_no_daystate_at_all_recovers_nothing(self):
        """No day-state file means the batch has recorded nothing, so nothing
        has failed yet — there is nothing for a re-seed to pick up."""
        from automations.day_orchestrator import state as day_state
        cfg = [mock.Mock(report_id="daily_focus", source_type="appstream",
                         machine="Lucy 1", order=0)]
        with mock.patch("automations.day_orchestrator.registry.load_config",
                        return_value={}), \
             mock.patch("automations.day_orchestrator.registry.scheduled_today",
                        return_value=cfg), \
             mock.patch.object(day_state, "STATE_DIR", self.tmp):
            out = w._appstream_reports_to_rerun(dt.datetime(2026, 8, 29, 5, 29))
        self.assertEqual(out, [])

    def test_an_unreadable_state_recovers_nothing_rather_than_guessing(self):
        """It used to fall back to ['daily_focus'] — a blind rerun of a report
        that posts. The alert still carries the news either way."""
        with mock.patch("automations.day_orchestrator.registry.load_config",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(
                w._appstream_reports_to_rerun(dt.datetime(2026, 8, 29, 5, 29)), [])


class AlertWordingNoLongerBlamesTheLogin(unittest.TestCase):
    def test_unhealthy_reason_describes_the_report_impact(self):
        """The ping text is what a human reads at 3am — it must name the real
        failure ('a report cannot open the console'), not a login nobody drives."""
        import inspect
        src = inspect.getsource(w.watch)
        self.assertIn("a report cannot open the ", src)
        self.assertNotIn("the self-heal is BROKEN", src)


if __name__ == "__main__":
    unittest.main()
