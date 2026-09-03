"""The login rules for the fleet, as tests. Megan 2026-09-02.

Five rules came out of the 4am failures, and every one of them had already been
written down somewhere as a comment before it broke. Comments do not fail a
build, so they are here instead:

  1. TWO ACCOUNTS, EVER. 'Lucy Reports' runs every report on every Lucy;
     'Lucy Resume Pushing' runs the resume pusher. rcaptain and the CarlosNLR
     'alt' slot are RETIRED and must not be selectable.
  2. THE USERNAME HAS A SPACE. "Lucy Reports", not "LucyReports" — a mangled one
     reaches a console that renders with no token, which every layer above reads
     as success. That is the bug that killed the 4am batch on 2026-09-02.
  3. OWNERVILLE LOGS IN AT ownerville.com, not v2.ownerville.com.
  4. NEITHER LOGIN NEEDS A HUMAN. The Cloudflare box clears itself given ~20-30s
     before submit, on BOTH ownerville and AppStream.
  5. NO MACHINE DEPENDS ON ANOTHER. Nothing is a "consumer"; nothing is pushed a
     session; a failure is diagnosed and fixed on the machine it happened on.

    python -m unittest automations.shared.test_login_policy -v
"""
from __future__ import annotations

import re
import unittest
from unittest import mock

from automations.shared import creds
from automations.shared import login_check as lc


class OnlyTwoAccountsExist(unittest.TestCase):

    def test_the_retired_names_are_refused(self):
        for name in ("alt", "rcaptain", "carlos", "carlosnlr", "primary2"):
            with self.subTest(account=name):
                with self.assertRaises(RuntimeError) as cm:
                    creds.appstream_account(name)
                self.assertIn("RETIRED", str(cm.exception).upper())

    def test_the_two_that_exist_are_the_only_ones_allowed(self):
        self.assertEqual(tuple(creds.ALLOWED_APPSTREAM_ACCOUNTS),
                         ("primary", "lucyresume"))

    def test_the_alt_slot_can_never_be_selected_again(self):
        """Even with a leftover appstream-alt.json sitting on the machine.

        The danger is not a missing file, it is a PRESENT one: an old install
        still carrying the CarlosNLR credential, waiting for a call site nobody
        updated. has_appstream_alt() is hard-False so no code path lights up."""
        with mock.patch.object(creds, "_alt_file", return_value={
                "appstream_alt_username": "CarlosNLR",
                "appstream_alt_password": "x"}):
            self.assertFalse(creds.has_appstream_alt())
            self.assertNotIn("alt", creds.appstream_accounts())
            # ...but it IS reported, so somebody deletes it.
            self.assertTrue(any("alt" in s
                                for s in creds.unexpected_appstream_accounts()))

    def test_no_report_may_ask_for_an_account_by_a_name_we_do_not_know(self):
        """Never fall back to a broader login — that is the 8/30 over-push.

        The resume pusher is scoped to two offices by its ACCOUNT's permissions.
        A missing scoped credential must fail, never silently resolve to the
        reporting login, which can see all 28 and whose send-to-AI is
        irreversible."""
        with self.assertRaises(RuntimeError):
            creds.appstream_account("something_nobody_installed")


class TheUsernameHasASpaceInIt(unittest.TestCase):

    def test_the_mangled_spellings_are_repaired(self):
        for wrong in ("LucyReports", "lucyreports", "lucy_reports",
                      "LUCY  REPORTS", " Lucy-Reports "):
            with self.subTest(given=wrong):
                self.assertEqual(creds.canonical_appstream_username(wrong),
                                 "Lucy Reports")

    def test_the_resume_login_is_repaired_the_same_way(self):
        self.assertEqual(
            creds.canonical_appstream_username("LucyResumePushing"),
            "Lucy Resume Pushing")

    def test_an_account_we_do_not_know_is_left_alone(self):
        """This repairs a spelling we are certain of. It does not invent logins."""
        self.assertEqual(creds.canonical_appstream_username("SomeoneElse"),
                         "SomeoneElse")
        self.assertEqual(creds.canonical_appstream_username(""), "")

    def test_the_two_canonical_names_are_the_allowed_accounts(self):
        self.assertEqual(creds._CANONICAL_APPSTREAM_USERNAMES,
                         ("Lucy Reports", "Lucy Resume Pushing"))


class OwnervilleLogsInAtTheRootDomain(unittest.TestCase):

    def test_the_login_url_is_not_v2(self):
        from automations.shared import tableau_patchright as tp
        self.assertEqual(tp.LOGIN_URL.rstrip("/"), "https://ownerville.com")
        self.assertNotIn("v2.", tp.LOGIN_URL)

    def test_every_module_that_drives_the_login_uses_it(self):
        """v2 is the internal dashboard behind the login, not the login page.

        Pinned because the two URLs are one character apart and a login pointed
        at v2 fails in the confusing direction: the page loads, so it reads as a
        credential problem rather than a wrong address."""
        import inspect
        from automations.shared import tableau_patchright as tp
        from automations.shared import appstream_autorenew as ar
        from automations.shared import session_holder as sh
        for mod in (tp, ar, sh):
            src = inspect.getsource(mod)
            for line in src.splitlines():
                if "goto(" not in line or "ownerville" not in line:
                    continue
                if "v2.ownerville" in line:
                    # A DATA page (index.cfm?p=NNN) legitimately lives on v2;
                    # a bare login navigation must not.
                    self.assertIn("p=", line,
                                  "%s: login navigation must use ownerville.com, "
                                  "not v2 — %s" % (mod.__name__, line.strip()))


class NeitherLoginNeedsAHuman(unittest.TestCase):

    def test_the_cloudflare_waits_are_long_enough(self):
        """Megan: "you type the UN and submit then the PW and WAIT 20-30 sec".

        At 3s the submit landed mid-check and the login failed, which read as
        "a human is required" for twelve days. Lowering these to speed a login
        up IS the bug — hence a floor, asserted."""
        from automations.shared import tableau_patchright as tp
        self.assertGreaterEqual(tp._CLOUDFLARE_WAIT_MS, 20_000)
        self.assertGreaterEqual(tp._PRE_SUBMIT_PAUSE_MS, 20_000)

    def test_one_form_driver_serves_both_systems(self):
        """Ownerville and AppStream use the SAME two-step form, so they share
        the driver — which is how the wait can never be right on one and wrong
        on the other."""
        import inspect
        from automations.shared import tableau_patchright as tp
        src = inspect.getsource(tp._drive_login_form)
        self.assertIn("_CLOUDFLARE_WAIT_MS", src)
        self.assertIn("_PRE_SUBMIT_PAUSE_MS", src)
        # The pause is after the password is filled and before submit.
        self.assertLess(src.index("_PRE_SUBMIT_PAUSE_MS"), src.index("Submitting"))

    def test_a_scheduled_run_may_drive_the_appstream_form(self):
        from automations.shared import tableau_patchright as tp
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("APPSTREAM_NO_FORM_LOGIN", None)
            self.assertTrue(tp._appstream_form_login_allowed(
                allow_form_login=False, force_form_login=False,
                username=None, password=None))


class NoMachineDependsOnAnother(unittest.TestCase):

    def test_nothing_is_a_consumer(self):
        from automations.shared import tableau_patchright as tp
        from automations.shared import appstream_autorenew as ar
        self.assertIsNone(tp._appstream_consumer_of())
        self.assertEqual(ar._consumer_of(), "")

    def test_the_dead_session_error_points_at_this_machine(self):
        from automations.shared import tableau_patchright as tp
        msg = str(tp._appstream_reseed_error("the token is stale"))
        self.assertIn("this machine", msg.lower())
        self.assertNotIn("--appstream-push-fleet", msg)
        self.assertNotIn("CONSUMER", msg)

    def test_the_queue_action_that_pushed_a_session_is_retired(self):
        from automations.day_orchestrator import mini_control as mc
        ok, msg = mc._action_push_appstream_fleet("")
        self.assertFalse(ok)
        self.assertIn("RETIRED", msg.upper())

    def test_the_watch_never_suppresses_a_page_on_another_machines_health(self):
        from automations.shared import appstream_watch as w
        fed, why = w.fleet_is_feeding_us()
        self.assertFalse(fed)
        self.assertIn("this machine", why.lower())


class BothLoginsAreCheckedSeparately(unittest.TestCase):
    """"Ownerville and App stream ARE NOT the same login and should not be
    considered fixed if only one of them works" (Megan 2026-09-02)."""

    def _run(self, ov_ok, as_ok, acct_ok=True):
        with mock.patch.object(lc, "_is_appstream_runner", return_value=True), \
             mock.patch.object(lc, "check_ownerville", return_value={
                 "system": "Ownerville", "ok": ov_ok, "detail": "ov"}), \
             mock.patch.object(lc, "check_appstream", return_value={
                 "system": "AppStream", "ok": as_ok, "detail": "as"}), \
             mock.patch.object(lc, "check_accounts", return_value={
                 "system": "Accounts", "ok": acct_ok, "detail": "acct"}):
            return lc.run()

    def test_one_passing_is_not_enough(self):
        self.assertFalse(self._run(ov_ok=True, as_ok=False)["ok"])
        self.assertFalse(self._run(ov_ok=False, as_ok=True)["ok"])

    def test_both_passing_is(self):
        self.assertTrue(self._run(ov_ok=True, as_ok=True)["ok"])

    def test_a_bad_account_fails_even_with_two_live_sessions(self):
        """A live session minted by a retired login is not a pass — that is how
        a machine keeps working as an account nobody configured."""
        self.assertFalse(self._run(ov_ok=True, as_ok=True, acct_ok=False)["ok"])

    def test_every_system_is_reported_by_name(self):
        got = {r["system"] for r in self._run(ov_ok=True, as_ok=False)["results"]}
        self.assertEqual(got, {"Ownerville", "AppStream", "Accounts"})

    def test_a_machine_that_is_not_a_runner_is_not_a_failure(self):
        """Megan's laptop: the rcaptain keychain pair was deliberately deleted.
        A check that is red by design gets ignored on the morning it is red for
        real."""
        with mock.patch.object(lc, "_is_appstream_runner", return_value=False), \
             mock.patch.object(lc, "check_ownerville", return_value={
                 "system": "Ownerville", "ok": True, "detail": "ov"}):
            self.assertTrue(lc.run()["ok"])

    def test_the_machine_name_says_when_it_is_a_guess(self):
        """_this_machine() silently defaults to "Lucy 1" with no marker, so a
        header naming a machine may be naming the wrong one."""
        from automations.shared import session_holder as sh
        import pathlib as _pl
        missing = _pl.Path("/nonexistent/.machine-profile")
        with mock.patch.object(sh, "_MACHINE_MARKER", missing):
            self.assertIn("ASSUMED", lc._machine())

    def test_the_ownerville_account_is_asserted_per_machine(self):
        """Presence was never the question — WHICH account is.

        On 2026-09-01 Lucy 1's file said `chidalgo` and nothing errored: Raf's
        board came back empty, Calvin and Jay vanished as "name not found in
        ownerville", and it cost an afternoon. A check reporting "ownerville
        credential: present" passes that run."""
        self.assertEqual(lc.EXPECTED_OWNERVILLE_ACCOUNT,
                         {"Lucy 1": "rhidalgo", "Lucy 2": "chidalgo",
                          "Lucy 3": "rhidalgo"})
        with mock.patch.object(lc, "_expected_ownerville_account",
                               return_value="rhidalgo"), \
             mock.patch.object(creds, "ownerville_username",
                               return_value="chidalgo"), \
             mock.patch.object(creds, "appstream_username",
                               return_value="Lucy Reports"), \
             mock.patch.object(creds, "unexpected_appstream_accounts",
                               return_value=[]):
            res = lc.check_accounts()
        self.assertFalse(res["ok"])
        self.assertIn("chidalgo", res["detail"])
        self.assertIn("rhidalgo", res["detail"])

    def test_the_right_ownerville_account_passes(self):
        with mock.patch.object(lc, "_expected_ownerville_account",
                               return_value="rhidalgo"), \
             mock.patch.object(creds, "ownerville_username",
                               return_value="Rhidalgo"), \
             mock.patch.object(creds, "appstream_username",
                               return_value="Lucy Reports"), \
             mock.patch.object(creds, "unexpected_appstream_accounts",
                               return_value=[]):
            # Case must not matter — the login screen shows it capitalised.
            self.assertTrue(lc.check_accounts()["ok"])

    def test_an_unmarked_machine_asserts_nothing(self):
        """Otherwise every laptop fails, and someone 'fixes' it by installing
        Raf's login on a box that should not have it."""
        from automations.shared import session_holder as sh
        import pathlib as _pl
        with mock.patch.object(sh, "_MACHINE_MARKER",
                               _pl.Path("/nonexistent/.machine-profile")):
            self.assertIsNone(lc._expected_ownerville_account())

    def test_the_machine_name_is_plain_when_the_marker_is_real(self):
        from automations.shared import session_holder as sh
        with mock.patch.object(sh, "_this_machine", return_value="Lucy 3"), \
             mock.patch.object(sh._MACHINE_MARKER.__class__, "read_text",
                               lambda self: "Lucy 3\n"):
            self.assertEqual(lc._machine(), "Lucy 3")


if __name__ == "__main__":
    unittest.main()
