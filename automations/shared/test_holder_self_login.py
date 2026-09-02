"""The holder logs ownerville back in ITSELF. No human, at any hour.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_holder_self_login

WHY (Megan 2026-09-02, in as many words: "NO HUMAN IS REQUIRED"). Every recovery
path in session_holder ended at a prompt in a Chrome window nobody is sitting in
front of. On the night of 2026-09-01 that read:

    [23:48:28] no live rqst token and the mint failed — asking for a restart
    [23:54:28] exiting (rc=1) so launchd relaunches the holder
    [23:54:31] SEED: log into ownerville in the window and clear any
               'verify you're human' box. Waiting up to 15 min…

Nobody was there at midnight. Ownerville stayed dark through the 4am batch —
applicant_sync_morning, recruiter_retention_daily and daily_focus all failed —
until a human logged in at 08:26. The relaunch ladder could not save it: it
re-seeds from the persistent profile's cookies, and those cookies were dead.

The premise that justified waiting ("never do a fresh login, Cloudflare will
challenge it") was measured false the day before, on Lucy 1 2026-09-01:
"ownerville form login reached a LIVE session UNATTENDED (rqst present)". That
is why appstream_autorenew.refresh_ownerville exists and works. The holder just
never picked it up.

This file pins the three things that must stay true:
  1. a cold session gets the FORM DRIVEN, not a prompt printed;
  2. success is judged on the SESSION being live, never on the form being typed
     into (ownerville can redirect straight past the form when already signed in
     — the mistake refresh_ownerville had to correct);
  3. a human mid-login is still never navigated out from under (passive check
     runs first), and a failing login is throttled instead of hammered.

[[feedback_lucys_always_warm]]
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import inspect
import unittest
from unittest import mock

from automations.shared import session_holder as sh


class _Page:
    """Enough page for the login helper. `valid` decides what the session check
    sees; `drive_raises` reproduces 'already signed in so the fill timed out'."""

    def __init__(self, drive_raises=False):
        self.drive_raises = drive_raises
        self.goto_urls = []

    def goto(self, url, **kw):
        self.goto_urls.append(url)

    def wait_for_timeout(self, ms):
        pass


class _Ctx:
    def storage_state(self):
        return {"cookies": [{"domain": "ownerville.com", "name": "rqst_ABC"}]}


class UnattendedLoginTest(unittest.TestCase):

    def setUp(self):
        sh._LAST_LOGIN_ATTEMPT.clear()

    def _run(self, valid, drive_raises=False):
        page = _Page(drive_raises=drive_raises)

        def _drive(pg, **kw):
            if drive_raises:
                raise TimeoutError("password fill timed out")

        with mock.patch.object(sh, "_drive_login_form", side_effect=_drive), \
             mock.patch.object(sh, "_ownerville_session_valid",
                               return_value=valid), \
             mock.patch.object(sh, "_export_ownerville", return_value=6):
            ok = sh._unattended_ownerville_login(_Ctx(), page, verbose=False)
        return ok, page

    def test_it_drives_the_form_and_reports_success(self):
        ok, page = self._run(valid=True)
        self.assertTrue(ok, "a live session after the login must count as success")
        self.assertTrue(page.goto_urls, "it must navigate to the login page")

    def test_already_signed_in_is_not_a_failure(self):
        """The form throwing does NOT mean the session is bad — ownerville can
        redirect past the form entirely. Judge the session, not the typing."""
        ok, _ = self._run(valid=True, drive_raises=True)
        self.assertTrue(
            ok, "a live session must win even when the form could not be driven")

    def test_a_dead_session_is_a_failure(self):
        ok, _ = self._run(valid=False)
        self.assertFalse(ok, "no live rqst afterwards is not a successful login")

    def test_it_never_clobbers_a_good_export_on_failure(self):
        page = _Page()
        with mock.patch.object(sh, "_drive_login_form"), \
             mock.patch.object(sh, "_ownerville_session_valid",
                               return_value=False), \
             mock.patch.object(sh, "_export_ownerville") as exp:
            sh._unattended_ownerville_login(_Ctx(), page, verbose=False)
        exp.assert_not_called()

    def test_it_is_throttled(self):
        """A login retried every 6-minute cycle all night is how you EARN a
        challenge. One attempt per LOGIN_MIN_INTERVAL_MIN."""
        ok1, _ = self._run(valid=False)
        ok2, page2 = self._run(valid=False)
        self.assertFalse(ok1)
        self.assertFalse(ok2)
        self.assertEqual([], page2.goto_urls,
                         "the second attempt inside the window must not navigate")

    def test_an_exception_never_takes_the_holder_down(self):
        page = _Page()
        with mock.patch.object(sh, "_drive_login_form"), \
             mock.patch.object(sh, "_ownerville_session_valid",
                               side_effect=RuntimeError("browser gone")):
            self.assertFalse(
                sh._unattended_ownerville_login(_Ctx(), page, verbose=False))


class TheRecoveryPathsActuallyCallItTest(unittest.TestCase):
    """The helper existing is worth nothing if main() still prints a prompt and
    waits — which is exactly how two earlier holder fixes came to sit inert."""

    def setUp(self):
        self.src = inspect.getsource(sh.main)

    def test_the_stale_branch_logs_in_before_it_asks_for_a_human(self):
        stale = self.src.split("Healthy → navigate the one tab")[1]
        self.assertIn(
            "_unattended_ownerville_login", stale,
            "a stale session must drive the login, not just set awaiting_login")
        self.assertLess(
            stale.index("_unattended_ownerville_login"),
            stale.index("awaiting_login = True"),
            "the unattended login must be TRIED BEFORE falling back to a human")

    def test_the_awaiting_login_branch_retries_instead_of_only_waiting(self):
        waiting = self.src.split("if awaiting_login:")[1].split("else:")[0]
        self.assertIn(
            "_unattended_ownerville_login", waiting,
            "'waiting for ownerville login…' every cycle for hours is the bug")
        self.assertLess(
            waiting.index("_passive_rqst"),
            waiting.index("_unattended_ownerville_login"),
            "the PASSIVE human check must run first — never navigate a tab "
            "someone is mid-login on (the 2026-06-18 bug)")

    def test_the_seed_tries_unattended_before_printing_the_prompt(self):
        seed = self.src.split("--- Seed")[1].split("AppStream warming")[0]
        self.assertIn("_unattended_ownerville_login", seed)
        self.assertLess(
            seed.index("_unattended_ownerville_login"),
            seed.index("SEED: log into ownerville"),
            "a relaunch onto dead profile cookies must log itself in, not sit "
            "on the prompt until morning (the 2026-09-01 midnight case)")


if __name__ == "__main__":
    unittest.main()
