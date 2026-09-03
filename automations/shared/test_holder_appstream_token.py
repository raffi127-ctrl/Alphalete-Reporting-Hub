"""The holder must hold a live TOKEN, not a rendering console.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_holder_appstream_token

WHAT THIS GUARDS (Megan 2026-08-25). `_warm_appstream` used to return True the
moment `#searchMC` was present after a reload, and never reach its
storage_state branch. But `#searchMC` renders off CFID/CFTOKEN alone, and the
holder's own 6-minute reload keeps those alive indefinitely. So once the rqst
SSO token aged out, the holder sat warming a console carrying no token,
`_export_appstream` correctly refused to write (its guard: no token → keep the
last good export), and the loop printed:

    [2026-08-25 11:29:32] AppStream ✓ — 0 cookies (office-11580 console warm)

every six minutes, for days. Two separate defects in one line:

1. THE REMOTE RE-SEED COULD NOT REACH IT. `--appstream-push-fleet` writes a
   fresh token to APPSTREAM_STORAGE_STATE, and _reuse_appstream_storage_state
   re-reads that file on EVERY call — but the early return meant it was never
   called. The one process whose whole job is holding that session was the one
   process a successful push could not reach. Lucy 1 stayed tokenless all
   morning on 8/25 after an 08:42 push that verified clean on all three boxes.

2. ✓ ON AN EMPTY EXPORT. The only signal that would have shown this read fine
   the entire time.

So the bar is the token now, and a 0-cookie export is reported as the problem
it is.
"""
from __future__ import annotations

import time
import unittest
from unittest import mock

from automations.shared import session_holder as sh


def _ctx(*, rqst: int, domain: str = "www.applicantstream.com",
         minutes_left: float | None = None):
    """A context whose storage_state carries `rqst` rqst_ tokens, optionally
    dated `minutes_left` minutes out (None = undated, as before)."""
    cookies = [{"name": "CFID", "domain": domain},
               {"name": "CFTOKEN", "domain": domain}]
    exp = ({"expires": time.time() + minutes_left * 60}
           if minutes_left is not None else {})
    cookies += [{"name": f"rqst_{i}", "domain": domain, **exp}
                for i in range(rqst)]
    ctx = mock.Mock()
    ctx.storage_state.return_value = {"cookies": cookies}
    return ctx


def _page(*, on_appstream: bool = True, searchmc: int = 1):
    page = mock.Mock()
    page.url = ("https://www.applicantstream.com/index.cfm?p=701"
                if on_appstream else "https://example.com/")
    page.locator.return_value.count.return_value = searchmc
    return page


class TheContextProbe(unittest.TestCase):
    """_ctx_rqst_count is what makes 'live' distinguishable from 'renders'."""

    def test_it_counts_applicantstream_rqst_cookies(self):
        self.assertEqual(sh._ctx_rqst_count(_ctx(rqst=2)), 2)

    def test_cf_cookies_alone_count_as_zero(self):
        """The exact shape of the bug: session cookies, no SSO token."""
        self.assertEqual(sh._ctx_rqst_count(_ctx(rqst=0)), 0)

    def test_another_domains_rqst_cookie_does_not_count(self):
        self.assertEqual(
            sh._ctx_rqst_count(_ctx(rqst=3, domain="ownerville.com")), 0)

    def test_a_broken_context_answers_zero_rather_than_raising(self):
        """A probe must never take the holder down."""
        ctx = mock.Mock()
        ctx.storage_state.side_effect = RuntimeError("browser gone")
        self.assertEqual(sh._ctx_rqst_count(ctx), 0)


class ARenderingConsoleIsNotEnough(unittest.TestCase):

    def test_console_with_no_token_falls_through_to_the_state_file(self):
        """THE BUG: a console that RENDERS must not short-circuit the recovery.

        #searchMC renders off CFID/CFTOKEN alone and the holder's own 6-minute
        reload keeps those alive indefinitely, so an early return on "the
        console is there" left the holder warming a tokenless session, exporting
        nothing, and printing ✓ every cycle (Lucy 1, all morning 2026-08-25).

        What the fall-through is FOR has changed. It used to be how a fleet push
        reached this process — a donor's token landed in the file and the holder
        picked it up. Nothing pushes between Lucys any more (2026-09-02: each
        signs in as its own account, so a push is an identity swap). The file is
        still re-read every call, which is how a re-seed run ON THIS MACHINE
        reaches the already-running holder. Same mechanism, local reason.

        The verdict follows the TOKEN, not the reuse: reuse returning True while
        the context still holds no rqst is not a live session, and saying it is
        would re-introduce the exact lie above."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            ok = sh._warm_appstream(_ctx(rqst=0), _page(), verbose=False)
        reuse.assert_called()          # the recovery path WAS reached
        self.assertFalse(ok, "a tokenless context is not a warm session, "
                             "however the storage_state replay reported")

    def test_console_with_a_token_short_circuits(self):
        """The healthy path must stay cheap — no re-read every 6 minutes."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            ok = sh._warm_appstream(_ctx(rqst=1), _page(), verbose=False)
        self.assertTrue(ok)
        reuse.assert_not_called()

    def test_a_dead_state_file_still_reports_failure(self):
        """Console renders, no token, and the saved state can't help either —
        that is a genuine 'needs a re-seed', not a success."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=False):
            self.assertFalse(
                sh._warm_appstream(_ctx(rqst=0), _page(), verbose=False))

    def test_off_console_goes_to_the_state_file_as_before(self):
        """Unchanged behaviour when the page isn't on applicantstream at all."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            sh._warm_appstream(_ctx(rqst=0), _page(on_appstream=False),
                               verbose=False)
        reuse.assert_called_once()

    def test_a_reload_that_throws_still_falls_through(self):
        page = _page()
        page.reload.side_effect = RuntimeError("navigation failed")
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            self.assertTrue(sh._warm_appstream(_ctx(rqst=1), page,
                                               verbose=False))
        reuse.assert_called_once()


class TheExportGuardIsUnchanged(unittest.TestCase):
    """_export_appstream's refusal to write a tokenless state is CORRECT — it
    protects a good rcaptain login. Only the reporting around it was wrong."""

    def test_a_tokenless_context_exports_nothing(self):
        self.assertEqual(sh._export_appstream(_ctx(rqst=0)), 0)

    def test_a_context_with_a_token_exports(self):
        # Swap the module-level Path for a Mock: a PosixPath's methods are
        # read-only, and this also guarantees no real file is written.
        fake = mock.Mock()
        with mock.patch.object(sh, "APPSTREAM_STORAGE_STATE", fake):
            n = sh._export_appstream(_ctx(rqst=1))
        self.assertEqual(n, 3)          # CFID + CFTOKEN + rqst_0
        fake.write_text.assert_called_once()

    def test_a_tokenless_context_never_touches_the_file(self):
        """The guard's real job: don't clobber the last good export."""
        fake = mock.Mock()
        with mock.patch.object(sh, "APPSTREAM_STORAGE_STATE", fake):
            sh._export_appstream(_ctx(rqst=0))
        fake.write_text.assert_not_called()


class ItRemintsBeforeTheTokenDies(unittest.TestCase):
    """THE TEN-HOUR HOLE (Lucy 1, 2026-08-27). Raising the bar to the token
    still left the holder re-hopping only AFTER the token had expired — the one
    moment `?rqst=<TOKEN>&p=701` has nothing live to trade in. Last good export
    08:38:46, token expired 08:41, then "console warm but NO rqst token" every
    six minutes until 6:41pm, when the 6pm ping finally told a human. Twenty
    healthy cycles inside the token's live window re-hopped exactly zero times,
    because a token in hand returned early no matter how little was left on it."""

    def test_a_token_with_hours_left_still_short_circuits(self):
        """The cheap path stays cheap — no re-hop every 6 min all day."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            ok = sh._warm_appstream(_ctx(rqst=1, minutes_left=95), _page(),
                                    verbose=False)
        self.assertTrue(ok)
        reuse.assert_not_called()

    def test_a_token_inside_the_margin_re_hops_while_it_can_still_mint(self):
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            ok = sh._warm_appstream(_ctx(rqst=1, minutes_left=12), _page(),
                                    verbose=False)
        self.assertTrue(ok)
        reuse.assert_called_once()

    def test_a_hop_that_mints_nothing_keeps_the_still_valid_token(self):
        """The old token has minutes left — that is warm, not stale. Reporting
        it stale here would fire a re-seed ping while the session still works."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=False):
            self.assertTrue(
                sh._warm_appstream(_ctx(rqst=1, minutes_left=5), _page(),
                                   verbose=False))

    def test_a_hop_that_throws_never_takes_the_holder_down(self):
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               side_effect=RuntimeError("navigation failed")):
            self.assertTrue(
                sh._warm_appstream(_ctx(rqst=1, minutes_left=5), _page(),
                                   verbose=False))

    def test_an_undated_token_is_dont_know_not_expiring(self):
        """Cookies with no `expires` must not send it re-hopping every cycle."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            sh._warm_appstream(_ctx(rqst=1), _page(), verbose=False)
        reuse.assert_not_called()


class TheExpiryProbe(unittest.TestCase):

    def test_it_reads_the_latest_rqst_expiry(self):
        left = sh._ctx_rqst_minutes_left(_ctx(rqst=1, minutes_left=42))
        self.assertAlmostEqual(left, 42, delta=1)

    def test_no_token_answers_dont_know(self):
        self.assertIsNone(sh._ctx_rqst_minutes_left(_ctx(rqst=0)))

    def test_a_broken_context_answers_dont_know_rather_than_raising(self):
        ctx = mock.Mock()
        ctx.storage_state.side_effect = RuntimeError("browser gone")
        self.assertIsNone(sh._ctx_rqst_minutes_left(ctx))


class TheLogCanTellRenewedFromStillAlive(unittest.TestCase):
    """THE REASON THIS GOT FIXED TEN TIMES (Megan 2026-08-27). `AppStream ✓ — 9
    cookies` printed identically whether the holder had just obtained a NEW
    login or was riding the same one down to its expiry. Every fix was judged
    against a signal that cannot distinguish the two, so "it renews itself
    overnight" went into the memory file on the strength of an expiry timestamp
    nobody had watched change. The ✓ has to name the token now."""

    def setUp(self):
        sh._LAST_RQST["id"] = None

    def test_it_names_the_token_and_its_remaining_life(self):
        note = sh._rqst_note(_ctx(rqst=1, minutes_left=90))
        self.assertIn("token ", note)
        self.assertIn("90m left", note)

    def test_riding_the_same_token_is_not_reported_as_renewal(self):
        ctx = _ctx(rqst=1, minutes_left=90)
        sh._rqst_note(ctx)
        self.assertNotIn("RENEWED", sh._rqst_note(ctx))

    def test_a_changed_token_is_called_out_as_renewed(self):
        """The one line that would have settled this ten fixes ago."""
        with mock.patch.object(sh, "_push_token_to_fleet"):
            sh._rqst_note(_ctx(rqst=1, minutes_left=5))
            ctx2 = _ctx(rqst=1, minutes_left=120)
            ctx2.storage_state.return_value["cookies"][-1]["name"] = "rqst_BRANDNEW1"
            self.assertIn("RENEWED", sh._rqst_note(ctx2))

    def test_a_donated_token_is_reported_as_received_not_renewed(self):
        """THE CONFOUND. A handoff changes the token id exactly like a renewal,
        so without this a machine that can never renew still prints RENEWED
        minutes after a donation lands — and the log goes back to meaning
        nothing, which is the whole thing this line was added to stop."""
        with mock.patch.object(sh, "_donated_token_ids", return_value={"BRANDNEW"}), \
             mock.patch.object(sh, "_push_token_to_fleet") as push:
            sh._rqst_note(_ctx(rqst=1, minutes_left=5))
            ctx2 = _ctx(rqst=1, minutes_left=120)
            ctx2.storage_state.return_value["cookies"][-1]["name"] = "rqst_BRANDNEW1"
            note = sh._rqst_note(ctx2)
        self.assertIn("RECEIVED", note)
        self.assertNotIn("RENEWED", note)
        push.assert_not_called()      # don't echo a donation back at the fleet

    def test_a_missing_marker_leaves_the_old_reading_intact(self):
        with mock.patch.object(sh, "_donated_token_ids", return_value=set()), \
             mock.patch.object(sh, "_push_token_to_fleet"):
            sh._rqst_note(_ctx(rqst=1, minutes_left=5))
            ctx2 = _ctx(rqst=1, minutes_left=120)
            ctx2.storage_state.return_value["cookies"][-1]["name"] = "rqst_BRANDNEW1"
            self.assertIn("RENEWED", sh._rqst_note(ctx2))

    def test_it_never_prints_the_whole_credential(self):
        ctx = _ctx(rqst=1)
        ctx.storage_state.return_value["cookies"][-1]["name"] = "rqst_" + "S" * 60
        self.assertNotIn("S" * 20, sh._rqst_note(ctx))

    def test_a_tokenless_context_adds_nothing(self):
        self.assertEqual(sh._rqst_note(_ctx(rqst=0)), "")

    def test_a_broken_context_adds_nothing_rather_than_raising(self):
        ctx = mock.Mock()
        ctx.storage_state.side_effect = RuntimeError("browser gone")
        self.assertEqual(sh._rqst_note(ctx), "")


class ARenewedTokenIsNeverHandedToAnotherLucy(unittest.TestCase):
    """A renewal stays on the machine that minted it. REVERSED 2026-09-02.

    This class used to assert the opposite — that Lucy 2's renewal was pushed to
    Lucy 1 and Lucy 3 — and both premises under that have since failed:

      * "Same account, same session, works on any of them." Not any more. Each
        Lucy signs in as its OWN login, so installing one machine's session on
        another does not refresh it, it REPLACES WHO THAT MACHINE IS, and every
        office lookup behind it silently becomes the wrong account's.
      * "The only route between them ran through a person clearing a Turnstile."
        There is no such person and never needed to be: the check clears itself
        given ~30s before submit, so a tokenless machine logs ITSELF back in.

    Megan 2026-09-02: "one machine CANNOT depend on another, we don't want 1
    taking them all down." The old design was exactly that dependency — three
    machines living off one donor's token.

    What is pinned now: the sender filters out every fellow hold machine, so
    with all three holding their own the push list is EMPTY and nothing goes out.
    The guard against distributing a tokenless file is kept as-is — it still
    protects the one remaining case, a machine added to the fleet before it has
    a login of its own."""

    def setUp(self):
        sh._LAST_RQST["id"] = None
        sh._LAST_FLEET_PUSH["at"] = 0.0

    def _renew(self, **kw):
        """Two cycles with different tokens = one renewal."""
        sh._rqst_note(_ctx(rqst=1, minutes_left=5))
        ctx2 = _ctx(rqst=1, minutes_left=120)
        ctx2.storage_state.return_value["cookies"][-1]["name"] = "rqst_BRANDNEW1"
        return sh._rqst_note(ctx2)

    def _mc(self):
        """A stand-in control queue, injected the way the holder imports it."""
        mc = mock.Mock()
        return mc, mock.patch.dict(
            "sys.modules", {"automations.day_orchestrator": mock.Mock(mini_control=mc),
                            "automations.day_orchestrator.mini_control": mc})

    def test_no_fellow_hold_machine_is_sent_the_session(self):
        """The whole point: with all three holding their own, nothing goes out."""
        mc, patch_mc = self._mc()
        with patch_mc, \
             mock.patch.object(sh, "_this_machine", return_value="Lucy 2"), \
             mock.patch.object(sh, "APPSTREAM_STORAGE_STATE",
                               mock.Mock(read_text=mock.Mock(
                                   return_value='{"cookies":[{"name":"rqst_NEW"}]}'))):
            self._renew()
        sent = [c.kwargs.get("machine") for c in mc.enqueue.call_args_list]
        self.assertEqual(sent, [],
                         "a renewal must not be pushed to a machine that holds "
                         "its own session — that is an identity swap")

    def test_a_non_holder_in_the_fleet_would_still_be_covered(self):
        """The filter is 'holds its own', not 'is a Lucy'.

        A machine added to APPSTREAM_FLEET_MACHINES before it has a login of its
        own has no other way to get a session, and that is the one case the push
        still exists for. Pinning it stops the filter being tightened into 'never
        push at all', which would strand such a machine silently."""
        mc, patch_mc = self._mc()
        with patch_mc, \
             mock.patch.object(sh, "_this_machine", return_value="Lucy 2"), \
             mock.patch.object(sh, "APPSTREAM_FLEET_MACHINES",
                               ("Lucy 1", "Lucy 2", "Lucy 3", "Newbox")), \
             mock.patch.object(sh, "APPSTREAM_STORAGE_STATE",
                               mock.Mock(read_text=mock.Mock(
                                   return_value='{"cookies":[{"name":"rqst_NEW"}]}'))):
            self._renew()
        sent = [c.kwargs.get("machine") for c in mc.enqueue.call_args_list]
        self.assertEqual(sent, ["Newbox"])

    def test_it_never_hands_itself_the_session(self):
        mc, patch_mc = self._mc()
        with patch_mc, \
             mock.patch.object(sh, "_this_machine", return_value="Lucy 2"), \
             mock.patch.object(sh, "APPSTREAM_STORAGE_STATE",
                               mock.Mock(read_text=mock.Mock(
                                   return_value='{"cookies":[{"name":"rqst_NEW"}]}'))):
            self._renew()
        self.assertNotIn("Lucy 2",
                         [c.kwargs.get("machine") for c in mc.enqueue.call_args_list])

    def test_a_tokenless_state_file_is_never_distributed(self):
        """The one thing worse than a dead session is three of them."""
        mc, patch_mc = self._mc()
        with patch_mc, \
             mock.patch.object(sh, "_this_machine", return_value="Lucy 2"), \
             mock.patch.object(sh, "APPSTREAM_STORAGE_STATE",
                               mock.Mock(read_text=mock.Mock(
                                   return_value='{"cookies":[{"name":"CFID"}]}'))):
            self._renew()
        mc.enqueue.assert_not_called()

    def test_a_renewal_bypasses_the_hourly_floor_for_a_machine_that_needs_it(self):
        """THE DEFECT (2026-08-28 19:47). Renewing invalidates the token the
        receiving machine is holding, so throttling THIS push leaves it on a dead
        one that still reads valid — Lucy 1 and Lucy 3 both on EA30849A showing
        "18m left" while Lucy 2 had moved to EC854530. An hour's delay is an hour
        of false health, not an hour of staleness.

        Still pinned, now against the only recipient that can exist: a fleet
        machine with no login of its own. Between Lucys nothing is sent at all,
        so the floor has nothing to throttle."""
        mc, patch_mc = self._mc()
        with patch_mc, \
             mock.patch.object(sh, "_this_machine", return_value="Lucy 2"), \
             mock.patch.object(sh, "APPSTREAM_FLEET_MACHINES",
                               ("Lucy 1", "Lucy 2", "Lucy 3", "Newbox")), \
             mock.patch.object(sh, "APPSTREAM_STORAGE_STATE",
                               mock.Mock(read_text=mock.Mock(
                                   return_value='{"cookies":[{"name":"rqst_NEW"}]}'))):
            self._renew()                       # first renewal: sets the floor
            n_first = mc.enqueue.call_count
            sh._LAST_RQST["id"] = "somethingelse"
            self._renew()                       # second renewal, seconds later
        self.assertGreater(mc.enqueue.call_count, n_first,
                           "a renewal must not wait out the floor")

    def test_the_alive_heartbeat_still_respects_the_floor(self):
        """The other trigger has nothing new to say, so it stays throttled —
        otherwise three healthy machines flood the queue every six minutes."""
        mc, patch_mc = self._mc()
        with patch_mc, \
             mock.patch.object(sh, "_this_machine", return_value="Lucy 2"), \
             mock.patch.object(sh, "APPSTREAM_STORAGE_STATE",
                               mock.Mock(read_text=mock.Mock(
                                   return_value='{"cookies":[{"name":"rqst_NEW"}]}'))):
            sh._push_token_to_fleet()
            n_first = mc.enqueue.call_count
            sh._push_token_to_fleet()
        self.assertEqual(mc.enqueue.call_count, n_first)

    # REPLACED 2026-08-28. This used to assert that a second renewal inside the
    # hour pushed nothing — it was written when the floor was believed to be a
    # pure cost control. It was the bug: a renewal invalidates the token the
    # other machines hold, so suppressing that push leaves them dead-but-
    # valid-looking for up to an hour. The floor's real job is bounding the
    # "I am alive" heartbeat, which is what the test above now pins. Kept as a
    # note rather than deleted, so nobody restores the old assertion as a fix.

    def test_riding_the_same_token_hands_off_nothing(self):
        """Only a renewal has anything new to give."""
        with mock.patch.object(sh, "_push_token_to_fleet") as push:
            ctx = _ctx(rqst=1, minutes_left=90)
            sh._rqst_note(ctx)
            sh._rqst_note(ctx)
        push.assert_not_called()

    def test_a_broken_queue_never_takes_the_holder_down(self):
        mc, patch_mc = self._mc()
        mc.enqueue.side_effect = RuntimeError("sheet unreachable")
        with patch_mc, \
             mock.patch.object(sh, "_this_machine", return_value="Lucy 2"), \
             mock.patch.object(sh, "APPSTREAM_STORAGE_STATE",
                               mock.Mock(read_text=mock.Mock(
                                   return_value='{"cookies":[{"name":"rqst_NEW"}]}'))):
            self.assertIn("RENEWED", self._renew())   # did not raise


class ZeroIsNotSuccess(unittest.TestCase):
    """The ✓ that hid it. Guarded at the source so the log can't lie again."""

    def test_the_loop_only_prints_the_check_when_something_was_exported(self):
        import inspect
        src = inspect.getsource(sh)
        self.assertIn("if apn:", src,
                      "a 0-cookie export must not print the ✓ line")
        self.assertIn("NO rqst token", src,
                      "the empty-export case needs its own visible warning")


if __name__ == "__main__":
    unittest.main()


class AThrottledMintIsNotAFailure(unittest.TestCase):
    """The in-margin branch must not ask for a restart on the clock alone.

    THE ARITHMETIC THAT MADE THIS FIRE EVERY TOKEN CYCLE (measured on Lucy 2 and
    Lucy 3, 2026-09-03). The holder wakes every 6 min; REMINT_MARGIN_MIN is 30,
    so a draining token gets about five in-margin cycles. MINT_MIN_INTERVAL_MIN
    is also 30, so only the FIRST of those actually attempts a mint — the rest
    return False because they were throttled. Counting those as failures reached
    MINT_FAILURES_BEFORE_RESTART every time and asked for a restart on a session
    that was about to renew itself normally.

    _mint_is_throttled's docstring already stated the rule ("callers that
    escalate on failure MUST check this first") and the tokenless path below it
    obeyed it. This branch did not."""

    def setUp(self):
        sh._MINT_FAILURES["n"] = 0
        sh._MINT_FAILURES["restart_wanted"] = False

    def _cycle(self, *, throttled):
        """One in-margin cycle whose hop fails, as it always does in reality."""
        page = _page()
        with mock.patch.object(sh, "_ctx_rqst_minutes_left", return_value=5.0), \
             mock.patch.object(sh, "_mint_is_throttled", return_value=throttled), \
             mock.patch.object(sh, "_mint_appstream_via_ownerville",
                               return_value=False), \
             mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=False):
            sh._warm_appstream(_ctx(rqst=1), page, verbose=False)

    def test_throttled_cycles_never_ask_for_a_restart(self):
        for _ in range(6):
            self._cycle(throttled=True)
        self.assertFalse(sh._MINT_FAILURES["restart_wanted"],
                         "a restart was requested on the throttle clock alone")
        self.assertEqual(sh._MINT_FAILURES["n"], 0,
                         "a throttled call must not count as a failure")

    def test_real_failures_still_escalate(self):
        """The backstop has to survive the fix — two genuine misses still ask."""
        for _ in range(sh.MINT_FAILURES_BEFORE_RESTART):
            self._cycle(throttled=False)
        self.assertTrue(sh._MINT_FAILURES["restart_wanted"])

    def test_the_message_does_not_credit_the_restart_with_minting(self):
        """The hop has never minted; the TYPED login is what does.

        The old line said the restart "is the path that actually mints", which
        sent diagnosis at the restart ladder instead of at the login."""
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            for _ in range(sh.MINT_FAILURES_BEFORE_RESTART):
                self._cycle(throttled=False)
        out = buf.getvalue()
        self.assertNotIn("path that actually mints", out)
        self.assertIn("typed login", out.lower())
        # Reaching here means BOTH paths missed, and the typed login missing is
        # the actionable half — it points at the credential, which is where the
        # 2026-09-02 outage actually was.
        self.assertIn("credential", out.lower())


class TheInMarginRemintActuallyRenews(unittest.TestCase):
    """Renew BEFORE the token dies — the thing this branch never once did.

    REMINT_MARGIN_MIN exists so a successor is minted while the old token is
    still alive. But the branch only ever called the ownerville hop, which has
    minted nothing ever (0 hits in 23k log lines on Lucy 2), so every real
    renewal happened on the TOKENLESS path instead — about 5 minutes after
    expiry (14:03 -> 16:08 on a 120m token). Reports landing in that gap each
    had to log themselves back in.

    The typed login is what mints, so the margin now calls it — once per
    unthrottled cycle, and judged on the TOKEN ID CHANGING rather than on the
    call returning True."""

    def setUp(self):
        sh._MINT_FAILURES["n"] = 0
        sh._MINT_FAILURES["restart_wanted"] = False

    def _cycle(self, *, throttled, login_ok, token_before, token_after):
        ids = iter([token_before, token_after])
        with mock.patch.object(sh, "_ctx_rqst_minutes_left", return_value=5.0), \
             mock.patch.object(sh, "_mint_is_throttled", return_value=throttled), \
             mock.patch.object(sh, "_mint_appstream_via_ownerville",
                               return_value=False), \
             mock.patch.object(sh, "_rqst_id", side_effect=lambda _c: next(ids)), \
             mock.patch.object(sh, "_appstream_form_login",
                               return_value=login_ok) as login, \
             mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=False):
            ok = sh._warm_appstream(_ctx(rqst=1), _page(), verbose=False)
        return ok, login

    def test_a_new_token_counts_as_a_renewal(self):
        ok, login = self._cycle(throttled=False, login_ok=True,
                                token_before="AAAA1111", token_after="BBBB2222")
        self.assertTrue(ok)
        login.assert_called_once()
        self.assertEqual(sh._MINT_FAILURES["n"], 0)
        self.assertFalse(sh._MINT_FAILURES["restart_wanted"])

    def test_the_same_token_back_is_not_a_renewal(self):
        """applicantstream can resume the live session instead of showing the
        form. That returns True while handing back the SAME token — a no-op that
        must not read as a renewal or reset the failure counter."""
        ok, _ = self._cycle(throttled=False, login_ok=True,
                            token_before="AAAA1111", token_after="AAAA1111")
        self.assertEqual(sh._MINT_FAILURES["n"], 1,
                         "an unchanged token was counted as a successful mint")

    def test_a_throttled_cycle_does_not_type_the_login(self):
        """One attempt per margin, not one every 6 minutes."""
        _, login = self._cycle(throttled=True, login_ok=True,
                               token_before="AAAA1111", token_after="BBBB2222")
        login.assert_not_called()

    def test_a_login_that_raises_never_breaks_the_holder(self):
        with mock.patch.object(sh, "_ctx_rqst_minutes_left", return_value=5.0), \
             mock.patch.object(sh, "_mint_is_throttled", return_value=False), \
             mock.patch.object(sh, "_mint_appstream_via_ownerville",
                               return_value=False), \
             mock.patch.object(sh, "_appstream_form_login",
                               side_effect=RuntimeError("browser gone")), \
             mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=False):
            sh._warm_appstream(_ctx(rqst=1), _page(), verbose=False)
