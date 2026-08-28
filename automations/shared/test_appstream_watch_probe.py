"""The watch must probe the path the REPORTS use, not the disabled login form.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_appstream_watch_probe

WHAT THIS GUARDS (Megan 2026-08-27: "this is already corrected — I haven't
touched it all day"). `selfheal_ok()` used to call appstream_direct_session with
force_form_login=True / allow_form_login=True — the rcaptain login form. Hours
earlier the same day, `d793ea3` had made that form off-limits to scheduled runs
(allow_form_login defaults False, gated by _appstream_form_login_allowed), so
no report had driven it since.

The result was a nightly false alarm: the 4am batch ran clean off the holder's
re-hopped session while the watch drove a route nothing uses, failed it, and
posted "the self-heal is BROKEN" to #claudecorrections-and-requests + two DMs.
On 2026-08-27 Lucy 1 finished 47/50 reports (3 clock-gated, none AppStream) on
a token the holder had re-minted overnight by itself, and the alert still fired.

So the bar is: probe with the SAME flags a scheduled report passes. If this test
fails because someone re-enabled the form here, the alert goes back to crying
wolf every night — check whether the reports' own default changed first.
"""
from __future__ import annotations

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
        sent = []
        dead = {"ok": False, "rqst_expiry": None, "hours_left": None,
                "what": "AppStream", "reason": "EXPIRED"}
        with mock.patch.object(w, "_now",
                               return_value=__import__("datetime").datetime(
                                   2026, 8, 27, hour, 0)), \
             mock.patch.object(w, "_load_state", return_value=dict(state or {})), \
             mock.patch.object(w, "_save_state") as save, \
             mock.patch.object(w, "_export_age_min", return_value=600.0), \
             mock.patch.object(w, "session_status",
                               side_effect=lambda p, what: {**dead, "what": what}), \
             mock.patch.object(w, "_appstream_reports_to_rerun", return_value=[]), \
             mock.patch.object(w, "selfheal_ok",
                               return_value=(probe_ok, "why")) as probe, \
             mock.patch.object(w, "_alert", side_effect=lambda t, d: sent.append(t)):
            w.watch(dry_run=True)
        return sent, probe, (save.call_args[0][0] if save.call_args else {})

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
