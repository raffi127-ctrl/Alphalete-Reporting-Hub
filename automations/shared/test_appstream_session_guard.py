"""Tests for the AppStream dead-session guard.

WHAT THIS LOCKS DOWN (Megan 2026-08-24). Five reports died at 4am on 8/24 —
daily_focus, applicant_sync_morning, recruiter_retention_daily/_weekly and
alphalete-org-run's Recruiting pull — and every one of them told
#claudecorrections-and-requests the same wrong thing: `Missing AppStream
credential 'appstream_username'`. The session had gone stale; the credential was
only ever wanted by the form-login fallback, which the 2026-08-20 release put a
human-check on. So an unattended run walked into a door it cannot open and
reported the doorknob.

Two rules came out of that. The second still holds; the FIRST was reversed on
2026-09-02, because the premise under it was measured wrong:

  1. WAS "a run nobody asked to drive the login form must NOT drive it".
     Megan proved on 2026-09-01 (appstream_autorenew) that the form completes
     unattended from a cold profile, so a scheduled run driving it is a
     self-heal, not a door it cannot open. Reuse still comes first; the form is
     now the fallback, and APPSTREAM_NO_FORM_LOGIN=1 is the way back to
     reuse-only.
  2. Whatever a dead session trips over on the way down, the message the channel
     gets must name the RE-SEED. Never a credential lookup as the headline.

    python -m unittest automations.shared.test_appstream_session_guard -v
"""
from __future__ import annotations

import os
import unittest

from automations.shared import tableau_patchright as tp


class FormLoginAllowed(unittest.TestCase):
    """Who may fall through to the login form."""

    def setUp(self):
        # The kill switch is read from the environment, so no test may inherit
        # whatever the machine running it happens to have set.
        self._saved = os.environ.pop("APPSTREAM_NO_FORM_LOGIN", None)

    def tearDown(self):
        os.environ.pop("APPSTREAM_NO_FORM_LOGIN", None)
        if self._saved is not None:
            os.environ["APPSTREAM_NO_FORM_LOGIN"] = self._saved

    def test_scheduled_run_may_self_heal(self):
        # Every 4am report calls appstream_direct_session(verbose=True) and
        # nothing else. Since 2026-09-02 that run may sign itself back in when
        # the saved session is dead — reuse is still tried first, upstream.
        self.assertTrue(tp._appstream_form_login_allowed(
            allow_form_login=False, force_form_login=False,
            username=None, password=None))

    def test_kill_switch_puts_a_machine_back_to_reuse_only(self):
        for val in ("1", "true", "YES", "on"):
            with self.subTest(value=val):
                os.environ["APPSTREAM_NO_FORM_LOGIN"] = val
                self.assertFalse(tp._appstream_form_login_allowed(
                    allow_form_login=False, force_form_login=False,
                    username=None, password=None))

    def test_kill_switch_is_off_unless_actually_set(self):
        # An empty or unrelated value must not silently disable the self-heal.
        for val in ("", "0", "false", "  "):
            with self.subTest(value=val):
                os.environ["APPSTREAM_NO_FORM_LOGIN"] = val
                self.assertTrue(tp._appstream_form_login_allowed(
                    allow_form_login=False, force_form_login=False,
                    username=None, password=None))

    def test_default_signature_is_reuse_first(self):
        # Reuse stays the primary path: nothing may default to skipping it.
        import inspect
        sig = inspect.signature(tp.appstream_direct_session)
        self.assertIs(sig.parameters["allow_form_login"].default, False)
        self.assertIs(sig.parameters["force_form_login"].default, False)

    def test_explicit_opt_in_may(self):
        self.assertTrue(tp._appstream_form_login_allowed(
            allow_form_login=True, force_form_login=False,
            username=None, password=None))
        self.assertTrue(tp._appstream_form_login_allowed(
            allow_form_login=False, force_form_login=True,
            username=None, password=None))

    def test_alt_account_credentials_may(self):
        # daily_focus --alt-appstream signs in as a DIFFERENT account than the
        # saved session on purpose — the form drive IS the point there.
        self.assertTrue(tp._appstream_form_login_allowed(
            allow_form_login=False, force_form_login=False,
            username="alt@example.com", password="s3cret"))

    def test_half_a_credential_is_not_an_opt_in(self):
        # A username with no password can't complete an alt-account form login;
        # treating it as consent would put us back in the "fails somewhere
        # downstream" hole. Measured against the kill switch, which is where
        # "did anyone actually ask for this?" is still the whole question.
        os.environ["APPSTREAM_NO_FORM_LOGIN"] = "1"
        for user, pwd in (("alt@example.com", None), (None, "s3cret"),
                          ("alt@example.com", ""), ("", "s3cret")):
            with self.subTest(username=user, password=pwd):
                self.assertFalse(tp._appstream_form_login_allowed(
                    allow_form_login=False, force_form_login=False,
                    username=user, password=pwd))

    def test_a_full_credential_beats_the_kill_switch(self):
        # --alt-appstream signs in as another account on purpose: reuse cannot
        # serve it, so opting a machine out of the self-heal must not disarm it.
        os.environ["APPSTREAM_NO_FORM_LOGIN"] = "1"
        self.assertTrue(tp._appstream_form_login_allowed(
            allow_form_login=False, force_form_login=False,
            username="alt@example.com", password="s3cret"))


class ReseedError(unittest.TestCase):
    """The message a dead session gives the channel."""

    def test_names_the_reseed_command(self):
        err = tp._appstream_reseed_error("the saved session has no live token")
        self.assertIsInstance(err, RuntimeError)
        self.assertIn("--appstream-login", str(err))
        self.assertIn("re-seed", str(err).lower())

    def test_carries_the_reason_through(self):
        err = tp._appstream_reseed_error("some specific reason here")
        self.assertIn("some specific reason here", str(err))

    def test_reason_owns_the_first_line(self):
        # The alert quotes line 1 as "Likely cause", so that line has to be
        # about the session and nothing else.
        err = tp._appstream_reseed_error("the token is stale",
                                         detail="Traceback …\n  and more")
        self.assertEqual(
            str(err).splitlines()[0],
            "AppStream session is not usable: the token is stale")

    def test_says_a_human_is_required(self):
        # The one fact that stops somebody re-running it and waiting: no
        # unattended run can clear the 8/20 human-check.
        self.assertIn("unattended", str(tp._appstream_reseed_error("x")))

    def test_credential_failure_still_leads_with_the_reseed(self):
        # The 8/24 shape: creds.appstream_username() raises, and the wrapped
        # message must NOT read as a setup mistake.
        cred_err = RuntimeError(
            "Missing AppStream credential 'appstream_username'. Add it to "
            "'ownerville-creds.json' …")
        err = tp._appstream_reseed_error(
            "the saved session is stale and the login form can't run either "
            "(no AppStream credentials on this machine)",
            detail=str(cred_err))
        first_line = str(err).splitlines()[0]
        self.assertIn("AppStream session is not usable", first_line)
        self.assertNotIn("Missing AppStream credential", first_line)
        # …while the detail is still there for whoever wants it.
        self.assertIn("Missing AppStream credential", str(err))


class FleetPushCoversEveryMachine(unittest.TestCase):
    """Every machine that runs AppStream reports must be in the fleet push.

    2026-08-24: the list ended at Lucy 2 behind a comment reading "extend here
    when Lucy 3 exists". Lucy 3 went live 8/21 and nobody did, so the daily
    re-seed silently covered two machines out of three for three days. Lucy 3
    runs alphalete_org_focus, whose Recruiting pull is AppStream, and that step
    failed on an expired session the morning this was found. Nothing reports a
    machine being absent from the list — it only surfaces as that machine's
    reports failing."""

    def _fleet_block(self) -> str:
        """The destination list itself — anchored on `_dests = [`, NOT on
        `args.appstream_push_fleet`, which also appears in an earlier argument
        guard and matched there on the first cut of this test."""
        import inspect
        src = inspect.getsource(tp)
        i = src.index("_dests = [")
        return src[i:src.index("]", i) + 1]

    def test_lucy_3_is_in_the_fleet(self):
        self.assertIn('"Lucy 3"', self._fleet_block(),
                      "Lucy 3 runs AppStream reports and must get the re-seed")

    def test_lucy_1_and_2_are_still_there(self):
        block = self._fleet_block()
        for m in ('"Lucy 1"', '"Lucy 2"'):
            self.assertIn(m, block)

    def test_the_alt_slot_is_not_in_the_daily_push(self):
        """The alt slot was REMOVED 2026-08-25 and must stay out.

        It failed its verify on every push after the 8/20 human-gate (the alt
        profile is another account, so the install falls through to a login
        form that can't complete unattended), and no scheduled report uses that
        account. Re-adding it here re-adds a daily red `failed` row that names
        no real problem. Ship the alternate account deliberately instead —
        --appstream-push-primary/--appstream-push-alt with --account."""
        self.assertNotIn("set_appstream_alt_state", self._fleet_block())


if __name__ == "__main__":
    unittest.main()
