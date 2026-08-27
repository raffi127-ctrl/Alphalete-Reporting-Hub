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
