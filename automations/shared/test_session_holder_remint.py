"""The holder must MINT a new rqst token, and must do it without tearing down
the live console session.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_session_holder_remint

THREE FAILURES TAUGHT THIS FILE ITS RULES, all on 2026-08-29, all of which put
a "Session re-seed needed" page in front of Megan while the batch was fine.

1. THE WRONG HOP. `_reuse_appstream_storage_state` replays a token we already
   hold (`?rqst=<SAVED>&p=701`) — it RESTORES a session, it never ISSUES one.
   The 8/27 re-mint margin was wired to it, so the holder re-hopped a dying
   token every cycle and minted nothing. It only ever recovered when something
   else minted: a fleet push, or a restart. Lucy 1: token 03F0A612 hit "1m
   left" at 08:04, the holder restarted on a code change at 08:10, and at 08:11
   it handed a fresh token to the fleet.

2. THE SILENT FAILURE. The first fix gated every message behind `verbose`, and
   the loop calls _warm_appstream(verbose=False). So the next mint failed and
   said NOTHING — token 083AE947 just counted down from 21m with no line
   saying why.

3. TEARING DOWN THE SESSION TO RENEW IT. The mint called
   `_sso_to_appstream(page)`, which navigates the CONSOLE tab to ownerville and
   back. That tears down the live AppStream session, so the hop back has to
   establish a NEW one — and a new session is exactly what the 2026-08-20
   Turnstile refuses. #searchMC never rendered (10:04, and again at 10:50 with
   a 15s wait and a retry). The fleet's shared token expired at 10:05 with no
   successor and all three machines went dark together.

   Ownerville was never the problem: it issued 43A275AE on demand at 10:04,
   unattended, while we still held 083AE947. The token was fine; applying it by
   walking the console tab away was not.

THE SHAPE THAT WORKS, and what this file pins: read the fresh token in its OWN
tab, leave the console session alone, and RE-KEY the console tab with
`?rqst=<NEW TOKEN>&p=701` — the identical navigation the reuse path and every
fleet push already use successfully.

THE RULES:
  • the console tab is NEVER navigated to ownerville;
  • "the hop ran" is not success — a new token id is;
  • wait for the console, never snapshot it with count();
  • every outcome speaks with verbose OFF;
  • a fleet push is picked up for free and tried BEFORE any mint — that is what
    carries a machine that cannot mint;
  • attempts are throttled; a failed mint costs a navigation, not the session;
  • nothing here may ever raise into the holder loop.
"""
from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from automations.shared import session_holder as h


@contextlib.contextmanager
def _mint_enabled():
    """Clear the throttle (and force the flag on) so a test exercises the mint
    itself rather than the once-per-30-min gate."""
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
    """The holder's AppStream console tab.

    `console_after` models a console that needs a moment to paint: the first N
    wait_for_selector calls time out, then it appears — the real 10:04 case,
    where an instant count() check threw away a good token."""

    def __init__(self, has_console=True, url="https://x.applicantstream.com/a",
                 console_after=0, lands_on=None):
        self.url = url
        # Where a goto() ends up. Ownerville redirects to a URL carrying the
        # rqst, so the landing URL is what the token is read from — not the one
        # we asked for. None = the URL we navigated to.
        self._lands_on = lands_on
        self._has = has_console
        self._waits = 0
        self._console_after = console_after
        self.reloaded = False
        self.gotos = []
        self.closed = False

    def reload(self, **kw):
        self.reloaded = True

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = self._lands_on or url

    def wait_for_timeout(self, ms):
        return None

    def evaluate(self, script):
        return ""

    def wait_for_selector(self, sel, timeout=None):
        assert sel == "#searchMC"
        self._waits += 1
        if not self._has or self._waits <= self._console_after:
            raise _Timeout("timed out waiting for #searchMC")
        return object()

    def locator(self, sel):
        assert sel == "#searchMC"
        return _Locator(1 if self._has else 0)

    def close(self):
        self.closed = True


def _mint(page=None, token="NEWTOK", ids=("OLD", "NEW"), left=118.0):
    """Run a mint with verbose OFF; return (result, page, everything printed)."""
    page = page or _Page()
    buf = io.StringIO()
    with _mint_enabled(), contextlib.redirect_stdout(buf), \
         mock.patch.object(h, "_stamp", return_value="T"), \
         mock.patch.object(h, "_fresh_rqst_from_ownerville", return_value=token), \
         mock.patch.object(h, "_rqst_id", side_effect=list(ids)), \
         mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=left):
        ok = h._mint_appstream_via_ownerville(object(), page, verbose=False)
    return ok, page, buf.getvalue()


class ItNeverWalksTheConsoleTabToOwnerville(unittest.TestCase):
    """FAILURE 3, THE ONE THAT KILLED THE FLEET. Renewing must not destroy the
    session being renewed."""

    def test_the_console_tab_only_ever_gets_the_rekey_url(self):
        ok, page, _ = _mint(token="FRESH")
        self.assertTrue(ok)
        self.assertEqual(
            page.gotos,
            ["https://applicantstream.com/index.cfm?rqst=FRESH&p=701"],
            "the console tab must only be re-keyed, never sent to ownerville")

    def test_it_does_not_use_sso_to_appstream_on_the_console_tab(self):
        """_sso_to_appstream is what navigated the tab away. If it comes back
        into this path, the Turnstile failure comes back with it."""
        with mock.patch.object(h, "_sso_to_appstream") as sso:
            _mint()
        sso.assert_not_called()

    def test_the_token_is_read_in_a_throwaway_tab_that_gets_closed(self):
        """_fresh_rqst_from_ownerville opens its own page so the console tab is
        untouched — and must not leak it."""
        scratch = _Page(lands_on="https://v2.ownerville.com/index.cfm?rqst=ABC")
        ctx = mock.Mock(new_page=mock.Mock(return_value=scratch))
        tok = h._fresh_rqst_from_ownerville(ctx)
        self.assertEqual(tok, "ABC")
        self.assertTrue(scratch.closed, "leaked the scratch ownerville tab")


class ReadingTheTokenFromOwnerville(unittest.TestCase):
    def test_it_reads_the_token_from_the_url(self):
        page = _Page(lands_on="https://v2.ownerville.com/index.cfm?rqst=TOK_123&x=1")
        ctx = mock.Mock(new_page=mock.Mock(return_value=page))
        self.assertEqual(h._fresh_rqst_from_ownerville(ctx), "TOK_123")

    def test_no_token_anywhere_is_None_not_a_raise(self):
        page = _Page(lands_on="https://v2.ownerville.com/index.cfm")
        ctx = mock.Mock(new_page=mock.Mock(return_value=page))
        self.assertIsNone(h._fresh_rqst_from_ownerville(ctx))

    def test_a_thrown_ownerville_is_None_not_a_raise(self):
        ctx = mock.Mock(new_page=mock.Mock(side_effect=RuntimeError("no tab")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(h._fresh_rqst_from_ownerville(ctx))


class SuccessIsANewTokenNothingLess(unittest.TestCase):
    def test_a_new_token_is_a_mint(self):
        ok, _, out = _mint(ids=("OLD", "NEW"))
        self.assertTrue(ok)
        self.assertIn("MINTED", out)
        self.assertIn("OLD -> NEW", out)

    def test_the_same_token_back_is_NOT_a_mint(self):
        """The 8/27 measurement: the hop runs, the id does not change."""
        ok, _, out = _mint(ids=("SAME", "SAME"))
        self.assertFalse(ok)
        self.assertIn("mint FAILED", out)
        self.assertIn("SAME", out)

    def test_no_token_from_ownerville_fails_before_touching_the_console(self):
        page = _Page()
        buf = io.StringIO()
        with _mint_enabled(), contextlib.redirect_stdout(buf), \
             mock.patch.object(h, "_stamp", return_value="T"), \
             mock.patch.object(h, "_fresh_rqst_from_ownerville", return_value=None), \
             mock.patch.object(h, "_rqst_id", return_value="OLD"):
            ok = h._mint_appstream_via_ownerville(object(), page, verbose=False)
        self.assertFalse(ok)
        self.assertEqual(page.gotos, [], "must not re-key with no token")
        self.assertIn("mint FAILED", buf.getvalue())


class ItWaitsForTheConsoleRatherThanSnapshottingIt(unittest.TestCase):
    """FAILURE from 10:04: a good token thrown away because #searchMC had not
    painted at the instant of the check."""

    def test_it_waits_rather_than_using_count(self):
        page = _Page()
        page.locator = lambda sel: _Locator(0)   # count() would say "no console"
        ok, _, out = _mint(page=page)
        self.assertTrue(ok, "still snapshotting with count() instead of waiting")
        self.assertIn("MINTED", out)

    def test_a_console_that_never_appears_fails_and_says_how_hard_it_tried(self):
        page = _Page(has_console=False)
        ok, _, out = _mint(page=page, ids=("OLD", "OLD"))
        self.assertFalse(ok)
        self.assertIn("#searchMC absent", out)


class AFailedMintIsNeverSilent(unittest.TestCase):
    """FAILURE 2. Every message must speak with verbose OFF — the holder's loop
    never passes verbose=True."""

    def test_every_failure_mode_names_itself(self):
        for label, kw in (
            ("same token", dict(ids=("SAME", "SAME"))),
            ("no console", dict(page=_Page(has_console=False), ids=("OLD", "OLD"))),
        ):
            with self.subTest(label):
                ok, _, out = _mint(**kw)
                self.assertFalse(ok)
                self.assertIn("mint FAILED", out)

    def test_success_says_so_too(self):
        ok, _, out = _mint()
        self.assertTrue(ok)
        self.assertIn("MINTED", out)


class TheMintIsGatedAndThrottled(unittest.TestCase):
    def test_the_flag_can_switch_it_off_entirely(self):
        page = _Page()
        with mock.patch.object(h, "MINT_VIA_OWNERVILLE", False), \
             mock.patch.object(h, "_fresh_rqst_from_ownerville") as fetch:
            self.assertFalse(h._mint_appstream_via_ownerville(object(), page))
        fetch.assert_not_called()
        self.assertEqual(page.gotos, [])

    def test_attempts_are_throttled(self):
        """v1 ran every ~6 min for an hour. Once per 30 min, max."""
        page = _Page()
        buf = io.StringIO()
        with _mint_enabled(), contextlib.redirect_stdout(buf), \
             mock.patch.object(h, "_stamp", return_value="T"), \
             mock.patch.object(h, "_fresh_rqst_from_ownerville",
                               return_value="TOK") as fetch, \
             mock.patch.object(h, "_rqst_id", side_effect=["OLD", "NEW", "NEW", "NEWER"]), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=118.0):
            first = h._mint_appstream_via_ownerville(object(), page)
            second = h._mint_appstream_via_ownerville(object(), page)
        self.assertTrue(first)
        self.assertFalse(second, "a second attempt inside the window must not run")
        fetch.assert_called_once()

    def test_off_does_not_mean_broken(self):
        """With the mint off the margin still falls through to the replay and
        the session is still reported healthy."""
        page = _Page()
        with mock.patch.object(h, "MINT_VIA_OWNERVILLE", False), \
             mock.patch.object(h, "_ctx_rqst_count", return_value=1), \
             mock.patch.object(h, "_ctx_rqst_minutes_left", return_value=12.0), \
             mock.patch.object(h, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            self.assertTrue(h._warm_appstream(object(), page))
        reuse.assert_called_once()


class TheMarginMintsInsteadOfReplaying(unittest.TestCase):
    """FAILURE 1. _warm_appstream inside REMINT_MARGIN_MIN."""

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
    The ten-hour outage of 2026-08-27."""

    @staticmethod
    def _warm_no_token(*, reuse_ok, tokens_after_reuse, mint_ok):
        page = _Page()
        with mock.patch.object(h, "_ctx_rqst_count",
                               side_effect=[0] + [tokens_after_reuse] * 4), \
             mock.patch.object(h, "_reuse_appstream_storage_state",
                               return_value=reuse_ok) as reuse, \
             mock.patch.object(h, "_mint_appstream_via_ownerville",
                               return_value=mint_ok) as mint:
            ok = h._warm_appstream(object(), page)
        return ok, reuse, mint

    def test_a_fleet_push_is_picked_up_without_a_mint(self):
        """A donor's fresh token lands in the file; the replay re-reads it.
        Cheapest path, and what carries a machine that cannot mint — try first."""
        ok, reuse, mint = self._warm_no_token(
            reuse_ok=True, tokens_after_reuse=1, mint_ok=True)
        self.assertTrue(ok)
        reuse.assert_called_once()
        mint.assert_not_called()

    def test_with_nothing_to_replay_it_mints(self):
        ok, _, mint = self._warm_no_token(
            reuse_ok=False, tokens_after_reuse=0, mint_ok=True)
        self.assertTrue(ok)
        mint.assert_called_once()

    def test_a_replay_that_renders_but_carries_no_token_still_mints(self):
        """'It rendered' must not count as recovered — #searchMC comes back off
        CFID/CFTOKEN while the token is gone."""
        ok, _, mint = self._warm_no_token(
            reuse_ok=True, tokens_after_reuse=0, mint_ok=True)
        self.assertTrue(ok)
        mint.assert_called_once()

    def test_everything_failing_reports_stale_rather_than_lying(self):
        ok, _, _ = self._warm_no_token(
            reuse_ok=False, tokens_after_reuse=0, mint_ok=False)
        self.assertFalse(ok)


class ExactlyOneMachineHoldsTheSession(unittest.TestCase):
    """THE REGRESSION MEGAN NAMED (2026-08-29): "before we added Lucy 3, the
    other two Lucys were working great and no re-seeding was needed."

    Until `a965a8a` (8/24 19:08) this was APPSTREAM_HOLD_MACHINE = "Lucy 2" — a
    single machine held a live console and every other runner consumed the
    session it pushed. That commit made all three hold one, and the re-seeding
    started.

    All three run the SAME rcaptain account, and _push_token_to_fleet already
    records why that eats itself: "Renewing appears to INVALIDATE the token the
    donor handed out last time — which every other machine is still holding."
    One holder is a clean handoff. Three are three consoles on one account
    invalidating each other every ~6 minutes, ending with all three holding
    something dead that still reads valid — the 8/29 outage exactly.

    If this test fails because someone re-added a holder, read that comment
    before deciding the extra holder is the fix. It was tried; it is what
    brought Megan the re-seeds."""

    def test_only_one_machine_holds_a_console(self):
        self.assertEqual(len(h.APPSTREAM_HOLD_MACHINES), 1,
                         "more than one holder on the same account — this is the "
                         "8/24 regression that caused the re-seeding")

    def test_every_runner_still_receives_the_pushed_session(self):
        """Holding is restricted; RECEIVING must not be. Lucy 1 and Lucy 3 run
        AppStream reports and stay alive on the donor's pushes."""
        for m in ("Lucy 1", "Lucy 2", "Lucy 3"):
            self.assertIn(m, h.APPSTREAM_FLEET_MACHINES)

    def test_the_donor_pushes_to_the_others_not_to_nobody(self):
        """The trap in restricting the hold list: _push_token_to_fleet used to
        iterate it, so a single-entry hold list would push to NOBODY and quietly
        strand the other two."""
        import ast
        import inspect
        src = inspect.getsource(h._push_token_to_fleet)
        self.assertIn("APPSTREAM_FLEET_MACHINES", src)
        tree = ast.parse(src).body[0]
        body = tree.body[1:] if ast.get_docstring(tree) else tree.body
        code = "\n".join(ast.dump(n) for n in body)
        self.assertNotIn("APPSTREAM_HOLD_MACHINES", code,
                         "pushing to the hold list strands every non-holder")

    def test_the_back_compat_singular_name_still_resolves(self):
        """It was APPSTREAM_HOLD_MACHINES[1] when the tuple had three entries —
        an IndexError waiting to happen on a one-entry tuple."""
        self.assertEqual(h.APPSTREAM_HOLD_MACHINE, h.APPSTREAM_HOLD_MACHINES[0])
        self.assertEqual(h.APPSTREAM_HOLD_MACHINE, "Lucy 2")


class ItNeverDrivesTheHumanGatedPaths(unittest.TestCase):
    def test_no_login_form_and_no_applicant_actions(self):
        """The form is human-gated ([[reference_appstream_turnstile]]), and
        p=604 sends and removes applicants. A keep-alive touches neither."""
        import ast
        import inspect
        for fn in (h._mint_appstream_via_ownerville, h._fresh_rqst_from_ownerville):
            tree = ast.parse(inspect.getsource(fn)).body[0]
            body = tree.body[1:] if ast.get_docstring(tree) else tree.body
            code = "\n".join(ast.dump(n) for n in body)
            self.assertNotIn("force_form_login", code)
            self.assertNotIn("allow_form_login", code)
            self.assertNotIn("604", code)


if __name__ == "__main__":
    unittest.main()
