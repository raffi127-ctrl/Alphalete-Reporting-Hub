"""The holder must MINT a new rqst token, not replay the dying one.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_session_holder_remint

WHAT THIS GUARDS (2026-08-29). There are two AppStream hops and only one of
them mints:

  • `_reuse_appstream_storage_state` replays a token we already hold
    (`?rqst=<SAVED TOKEN>&p=701`). It RESTORES a session; it never ISSUES one.
    Measured 8/27 with token-identity logging: the id was unchanged across
    every cycle inside the re-mint margin, then expired.
  • `_sso_to_appstream` asks v2.ownerville.com for a FRESH token and hops with
    it. That is where an rqst comes from — how the first seed gets one, and how
    a holder restart gets one.

The 2026-08-27 re-mint fix wired REMINT_MARGIN_MIN to the FIRST of those, so the
holder re-hopped a dying token every cycle and minted nothing. It only recovered
when something else minted: a fleet push, or a restart. On Lucy 1 on 8/29 token
03F0A612 counted down to `1m left` at 08:04, the holder restarted on a code
change at 08:10, and at 08:11 it handed a fresh token to the fleet — the restart
did what four re-hop cycles could not. Overnight nothing restarts it and no
console work is scheduled between midnight and 4am, so the token died and the
3:00 AM "Session re-seed needed" fired with the 4am batch an hour out.

HOW IT ENDED THE SAME DAY — the mint is OFF (MINT_VIA_OWNERVILLE = False).
Ownerville really does issue a fresh token unattended (10:04: it handed over
43A275AE while we held 083AE947), so the mechanism was right. What it cannot do
is turn that token into a console: every hop landed with #searchMC absent, with
proper waits and a re-navigation. That is the symptom the human-gated form
gives, so the 2026-08-20 Turnstile appears to refuse any NEW session — by SSO as
well as by form. An existing session continues fine. The fleet's shared token
expired at 10:05 with no successor and all three machines went dark together.

THE RULES:
  • "the hop ran" is not success — a new token id is;
  • a failed mint says WHY, with verbose off (a silent failure cost the first
    live attempt);
  • wait for the console, never snapshot it with count();
  • a fleet push is picked up for free and is tried BEFORE any ownerville
    round-trip — that is what carries a machine that cannot mint;
  • the mint stays off, and throttled when on: a path that cannot succeed must
    not re-navigate the holder's console every cycle;
  • off must not mean broken — the replay still runs and still reports healthy;
  • nothing here may ever raise into the holder loop.
"""
from __future__ import annotations

import contextlib
import unittest
from unittest import mock

from automations.shared import session_holder as h


@contextlib.contextmanager
def _mint_enabled():
    """MINT_VIA_OWNERVILLE is OFF by default and every attempt is throttled.
    These tests are about what the mint DOES once it runs, so switch it on and
    clear the throttle. The gate itself is covered by TheMintIsOffByDefault."""
    with mock.patch.object(h, "MINT_VIA_OWNERVILLE", True), \
         mock.patch.dict(h._LAST_MINT_ATTEMPT, {"at": 0.0}):
        yield


class _Locator:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n


class _Timeout(Exception):
    """Stands in for playwright's TimeoutError."""


class _Page:
    """A console page. `has_console` drives #searchMC.

    `console_after` models a console that needs a moment to paint: the first
    N wait_for_selector calls time out, then it appears. That is the real
    2026-08-29 10:04 failure — a good token whose console had not rendered when
    the instant count() check ran."""

    def __init__(self, has_console=True, url="https://x.applicantstream.com/a",
                 console_after=0):
        self.url = url
        self._has = has_console
        self._waits = 0
        self._console_after = console_after
        self.reloaded = False
        self.gotos = []

    def reload(self, **kw):
        self.reloaded = True

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = url

    def wait_for_selector(self, sel, timeout=None):
        assert sel == "#searchMC"
        self._waits += 1
        if not self._has or self._waits <= self._console_after:
            raise _Timeout("timed out waiting for #searchMC")
        return object()

    def locator(self, sel):
        assert sel == "#searchMC"
        return _Locator(1 if self._has else 0)


class TheMintIsOffByDefault(unittest.TestCase):
    """SWITCHED OFF 2026-08-29 after it failed in the wild — see
    MINT_VIA_OWNERVILLE. Ownerville does issue a new token, but the hop cannot
    turn it into a console (#searchMC absent every time, waits and a
    re-navigation included), which matches what the Turnstile does to a NEW
    session. A mint that cannot succeed still costs a console re-navigation
    every cycle, so it stays off until someone shows a hop rendering again."""

    def test_it_does_nothing_and_touches_nothing_while_off(self):
        with mock.patch.object(h, "_sso_to_appstream") as sso:
            self.assertFalse(
                h._mint_appstream_via_ownerville(object(), _Page()))
        sso.assert_not_called()

    def test_the_holder_still_replays_and_stays_warm_with_it_off(self):
        """Off must not mean broken: the margin falls through to the replay and
        the session is still reported healthy."""
        page = _Page()
        with mock.patch.object(h, "_ctx_rqst_count", return_value=1), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=12.0), \
             mock.patch.object(h, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            self.assertTrue(h._warm_appstream(object(), page))
        reuse.assert_called_once()

    def test_attempts_are_throttled_even_when_on(self):
        """It ran every ~6 min for over an hour on 8/29. Once per 30 min, max."""
        page = _Page()
        with _mint_enabled(), mock.patch.object(h, "_sso_to_appstream") as sso, \
             mock.patch.object(h, "_rqst_id", side_effect=["OLD", "NEW", "NEW", "NEWER"]), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=118.0):
            first = h._mint_appstream_via_ownerville(object(), page)
            second = h._mint_appstream_via_ownerville(object(), page)
        self.assertTrue(first)
        self.assertFalse(second, "a second attempt inside the window must not run")
        sso.assert_called_once()


class MintingGoesThroughOwnerville(unittest.TestCase):
    """_mint_appstream_via_ownerville: success is a NEW token, nothing less."""

    def test_a_new_token_is_a_mint(self):
        page = _Page()
        with _mint_enabled(), mock.patch.object(h, "_sso_to_appstream") as sso, \
             mock.patch.object(h, "_rqst_id", side_effect=["OLD", "NEW"]), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=118.0):
            self.assertTrue(h._mint_appstream_via_ownerville(object(), page))
        sso.assert_called_once()

    def test_the_same_token_back_is_NOT_a_mint(self):
        """The exact 8/27 measurement: the hop runs, the id does not change.
        Reporting that as success is what hid the bug for two days."""
        page = _Page()
        with _mint_enabled(), mock.patch.object(h, "_sso_to_appstream"), \
             mock.patch.object(h, "_rqst_id", side_effect=["SAME", "SAME"]):
            self.assertFalse(h._mint_appstream_via_ownerville(object(), page))

    def test_no_console_is_not_a_mint(self):
        page = _Page(has_console=False)
        with _mint_enabled(), mock.patch.object(h, "_sso_to_appstream"), \
             mock.patch.object(h, "_rqst_id", side_effect=["OLD", "NEW"]):
            self.assertFalse(h._mint_appstream_via_ownerville(object(), page))

    def test_a_thrown_ownerville_never_escapes(self):
        """Ownerville may be mid-refresh. That is a missed cycle, not a crash of
        the one process holding the session."""
        page = _Page()
        with _mint_enabled(), mock.patch.object(
                h, "_sso_to_appstream",
                side_effect=RuntimeError("ownerville login isn't valid")), \
             mock.patch.object(h, "_rqst_id", return_value="OLD"):
            self.assertFalse(h._mint_appstream_via_ownerville(object(), page))


class TheMarginMintsInsteadOfReplaying(unittest.TestCase):
    """_warm_appstream inside REMINT_MARGIN_MIN. THE REGRESSION ITSELF."""

    @staticmethod
    def _warm(minutes_left, *, mint_ok=True, reuse_ok=True, tokens=1):
        page = _Page()
        with mock.patch.object(h, "_ctx_rqst_count", return_value=tokens), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=minutes_left), \
             mock.patch.object(h, "_mint_appstream_via_ownerville",
                               return_value=mint_ok) as mint, \
             mock.patch.object(h, "_reuse_appstream_storage_state",
                               return_value=reuse_ok) as reuse:
            ok = h._warm_appstream(object(), page)
        return ok, mint, reuse

    def test_inside_the_margin_it_mints_and_does_not_replay(self):
        ok, mint, reuse = self._warm(12.0)
        self.assertTrue(ok)
        mint.assert_called_once()
        reuse.assert_not_called()   # replaying a dying token mints nothing

    def test_a_healthy_token_is_left_alone(self):
        """Well clear of expiry: no ownerville round-trip, no replay."""
        ok, mint, reuse = self._warm(95.0)
        self.assertTrue(ok)
        mint.assert_not_called()
        reuse.assert_not_called()

    def test_a_failed_mint_falls_back_to_replay_and_stays_warm(self):
        ok, mint, reuse = self._warm(12.0, mint_ok=False)
        self.assertTrue(ok, "a missed mint must not report the session stale")
        mint.assert_called_once()
        reuse.assert_called_once()

    def test_it_never_reports_stale_while_the_token_is_still_alive(self):
        ok, _, _ = self._warm(3.0, mint_ok=False, reuse_ok=False)
        self.assertTrue(ok)


class TheRecoveryPathCanStillMint(unittest.TestCase):
    """No live token at all — expired, or a console rendering off CFID/CFTOKEN.
    This is the ten-hour outage of 2026-08-27."""

    @staticmethod
    def _warm_no_token(*, reuse_ok, tokens_after_reuse, mint_ok):
        page = _Page(has_console=True, url="https://x.applicantstream.com/a")
        with mock.patch.object(h, "_ctx_rqst_count",
                               side_effect=[0] + [tokens_after_reuse] * 4), \
             mock.patch.object(h, "_reuse_appstream_storage_state",
                               return_value=reuse_ok) as reuse, \
             mock.patch.object(h, "_mint_appstream_via_ownerville",
                               return_value=mint_ok) as mint:
            ok = h._warm_appstream(object(), page)
        return ok, reuse, mint

    def test_a_fleet_push_is_picked_up_without_an_ownerville_trip(self):
        """A donor's fresh token lands in the file; replay re-reads it. This is
        what carries a machine that cannot mint at all — try it first."""
        ok, reuse, mint = self._warm_no_token(
            reuse_ok=True, tokens_after_reuse=1, mint_ok=True)
        self.assertTrue(ok)
        reuse.assert_called_once()
        mint.assert_not_called()

    def test_with_nothing_to_replay_it_mints(self):
        """The outage path: every saved token is dead, so replay yields no live
        token. It used to stop here and print 'NO rqst token' for ten hours."""
        ok, _, mint = self._warm_no_token(
            reuse_ok=False, tokens_after_reuse=0, mint_ok=True)
        self.assertTrue(ok)
        mint.assert_called_once()

    def test_a_replay_that_renders_but_carries_no_token_still_mints(self):
        """The subtle one: #searchMC comes back off CFID/CFTOKEN while the token
        is gone. 'It rendered' must not count as recovered."""
        ok, _, mint = self._warm_no_token(
            reuse_ok=True, tokens_after_reuse=0, mint_ok=True)
        self.assertTrue(ok)
        mint.assert_called_once()

    def test_everything_failing_reports_stale_rather_than_lying(self):
        ok, _, _ = self._warm_no_token(
            reuse_ok=False, tokens_after_reuse=0, mint_ok=False)
        self.assertFalse(ok)


class ItWaitsForTheConsoleLikeTheReportsDo(unittest.TestCase):
    """THE FIRST LIVE FAILURE (2026-08-29 10:04). Ownerville did its job — it
    handed over a genuinely NEW token (43A275AE…, not the 083AE947 we held) and
    the hop navigated to it. But `_sso_to_appstream` returns after a FIXED sleep
    and never confirms #searchMC, and the mint then asked `locator().count()`
    the instant it returned. A console that had not finished painting was called
    a failed mint, so the token kept counting down to expiry.

    `_reuse_appstream_storage_state` has always used wait_for_selector here.
    The mint path has to match it."""

    @staticmethod
    def _mint(page, ids=("OLD", "NEW")):
        import io
        buf = io.StringIO()
        with _mint_enabled(), contextlib.redirect_stdout(buf), \
             mock.patch.object(h, "_stamp", return_value="T"), \
             mock.patch.object(h, "_sso_to_appstream"), \
             mock.patch.object(h, "_rqst_id", side_effect=list(ids)), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=118.0):
            ok = h._mint_appstream_via_ownerville(object(), page, verbose=False)
        return ok, buf.getvalue()

    def test_it_waits_rather_than_snapshotting_with_count(self):
        """The regression in one assertion: a console that is NOT present at the
        instant of the check, but appears within the wait. The old code asked
        locator().count() and lost the mint; the new code waits for it."""
        page = _Page()
        page.locator = lambda sel: _Locator(0)   # count() would say "no console"
        ok, out = self._mint(page)
        self.assertTrue(ok, "still snapshotting with count() instead of waiting")
        self.assertIn("MINTED", out)

    def test_it_re_navigates_the_token_url_once_before_giving_up(self):
        page = _Page(url="https://applicantstream.com/index.cfm?rqst=ABC&p=701",
                     console_after=1)
        ok, out = self._mint(page)
        self.assertTrue(ok)
        self.assertEqual(page.gotos,
                         ["https://applicantstream.com/index.cfm?rqst=ABC&p=701"])

    def test_a_console_that_never_appears_still_fails_and_says_how_hard_it_tried(self):
        page = _Page(has_console=False,
                     url="https://applicantstream.com/index.cfm?rqst=ABC&p=701")
        ok, out = self._mint(page, ids=("OLD", "OLD"))
        self.assertFalse(ok)
        self.assertIn("#searchMC absent after 2 attempt(s)", out)

    def test_it_does_not_re_navigate_a_url_with_no_token(self):
        """Nothing to retry — re-loading a tokenless URL just burns 15s."""
        page = _Page(has_console=False, url="https://applicantstream.com/login")
        ok, out = self._mint(page, ids=("OLD", "OLD"))
        self.assertFalse(ok)
        self.assertEqual(page.gotos, [])
        self.assertIn("after 1 attempt(s)", out)


class AFailedMintIsNeverSilent(unittest.TestCase):
    """COST A REAL ATTEMPT (2026-08-29). The first deploy gated every mint
    message behind `verbose`, and the holder's loop calls
    _warm_appstream(verbose=False). So when the margin opened on token 083AE947
    the mint failed and the log said NOTHING — the token just counted down from
    21m with no explanation, exactly the silence this whole subsystem keeps
    getting caught by. Each failure mode must name itself with verbose OFF."""

    @staticmethod
    def _mint(page=None, ids=("OLD", "NEW"), raises=None, left=118.0):
        """Run a mint with verbose OFF and return (result, everything printed)."""
        import io
        buf = io.StringIO()
        sso = mock.patch.object(h, "_sso_to_appstream", side_effect=raises) \
            if raises else mock.patch.object(h, "_sso_to_appstream")
        with _mint_enabled(), contextlib.redirect_stdout(buf), \
             mock.patch.object(h, "_stamp", return_value="T"), sso, \
             mock.patch.object(h, "_rqst_id", side_effect=list(ids)), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=left):
            ok = h._mint_appstream_via_ownerville(
                object(), page or _Page(), verbose=False)
        return ok, buf.getvalue()

    def test_a_thrown_ownerville_says_so(self):
        ok, out = self._mint(raises=RuntimeError("ownerville login isn't valid"))
        self.assertFalse(ok)
        self.assertIn("mint FAILED", out)
        self.assertIn("ownerville login isn't valid", out)

    def test_the_same_token_back_says_so(self):
        """The failure we actually hit. It must name the token and the cause."""
        ok, out = self._mint(ids=("SAME", "SAME"))
        self.assertFalse(ok)
        self.assertIn("mint FAILED", out)
        self.assertIn("SAME", out)

    def test_a_console_that_never_rendered_says_so(self):
        ok, out = self._mint(page=_Page(has_console=False), ids=("OLD", "OLD"))
        self.assertFalse(ok)
        self.assertIn("mint FAILED", out)
        self.assertIn("#searchMC", out)

    def test_a_success_says_so_too(self):
        ok, out = self._mint()
        self.assertTrue(ok)
        self.assertIn("MINTED", out)
        self.assertIn("OLD -> NEW", out)


class ItMintsThroughOwnervilleNotTheLoginForm(unittest.TestCase):
    def test_the_margin_path_names_ownerville(self):
        """The login form is human-gated and off-limits to unattended runs
        ([[reference_appstream_turnstile]]). The holder's renewal must ride the
        ownerville session it already holds, never a form."""
        import inspect
        src = inspect.getsource(h._mint_appstream_via_ownerville)
        self.assertIn("_sso_to_appstream", src)
        self.assertNotIn("force_form_login", src)
        self.assertNotIn("allow_form_login", src)

    def test_it_does_not_drive_applicant_actions(self):
        """p=604 sends and removes applicants. A keep-alive must never touch it.

        Checks the CODE, not the docstring — the docstring says the word while
        promising the opposite."""
        import ast
        import inspect
        fn = ast.parse(inspect.getsource(h._mint_appstream_via_ownerville)).body[0]
        body = fn.body[1:] if ast.get_docstring(fn) else fn.body
        code = "\n".join(ast.dump(n) for n in body)
        self.assertNotIn("604", code)


if __name__ == "__main__":
    unittest.main()
