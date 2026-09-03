"""Tests for the account scoping that bounds what Applicant Push can push.

WHAT THIS LOCKS DOWN (Megan 2026-08-31). On 8/30 the push sent resumes to ~22
offices when it is allowed two. It bounds itself with an office SWITCH, but the
v2 batch grid's select-all -> Send To AI reaches whatever the ACCOUNT can see,
and the shared 'Raf - Captain' login sees all 28. Send-to-AI is irreversible.

Two independent guards come out of that, and both are tested here:

  1. SCOPE — the two ROTATION offices sign in as LucyResume, an account granted
     only those two. A permission the report cannot talk its way past.
  2. IDENTITY — before any send, the console's own 'Account No:' must match the
     account this run declared. That catches Carlos's case, which scoping alone
     does NOT cover: the run attaching over CDP to a Chrome another report
     already has open, carrying the BROAD login's cookies. The scoped credential
     is never used on that screen, so its permissions never apply.

    python -m unittest automations.resume_pushing.test_account_scope -v
"""
from __future__ import annotations

import unittest

from automations.applicant_push import offices
from automations.resume_pushing import run as rp


class _Page:
    def __init__(self, text): self._text = text
    def inner_text(self, _sel): return self._text


def _console(account_no, who="Lucy Resume Pushing"):
    return "Account No: %s ) | %s | rest" % (account_no, who)


def _fp(account_no, who="Lucy Resume Pushing"):
    """The fingerprint _page_account_no builds: company number AND user.

    The number alone is the COMPANY (23981 = Alphalete Marketing Call Center)
    and is the same for every login under it, so a number-only fingerprint
    cannot tell Lucy Reports from Lucy Resume Pushing — measured 2026-08-31."""
    return "%s/%s" % (account_no, who)


class OfficeScope(unittest.TestCase):
    def test_every_office_states_an_account(self):
        # Read with [] in activate(), so a row that forgot to state one is a
        # crash, not a silent inherit of the broad account.
        for oid, row in offices.OFFICES.items():
            with self.subTest(office=oid):
                self.assertTrue(str(row.get("account") or "").strip(),
                                "office %s states no account" % oid)

    def test_rotation_offices_use_the_scoped_account(self):
        # These two are the ONLY offices anything scheduled pushes.
        for oid in offices.ROTATION:
            self.assertEqual(offices.OFFICES[oid]["account"], "lucyresume")

    def test_every_office_uses_the_resume_account(self):
        """REVERSED 2026-09-02. This used to assert the OPPOSITE for the
        diagnostic rows — that they must NOT be on the scoped account, because
        "LucyResume cannot see them; a manual --office run there needs the broad
        login".

        Megan: "I'm telling you the resume pushing can ONLY HAPPEN on the Resume
        pushing login. If that's not correct, then get it fixed."

        The old test's reasoning was also backwards on its own terms. It read a
        row saying 'lucyresume' as evidence "the scoped account has been widened
        — the thing this whole change exists to prevent". A row cannot widen an
        account; permissions live on the account, not in this table. All the row
        decides is which login the run signs in as. Setting a diagnostic office
        to 'lucyresume' does not grant access to it — it makes that office
        UNREACHABLE, which is the guarantee doing its job."""
        for oid, row in offices.OFFICES.items():
            with self.subTest(office=oid):
                self.assertEqual(row["account"], offices.RESUME_ACCOUNT)

    def test_activate_refuses_a_row_that_names_another_account(self):
        """A table is edited by people. The rule must not be one typo away."""
        from unittest import mock
        bad = dict(offices.OFFICES[offices.DEFAULT_OFFICE], account="primary")
        with mock.patch.dict(offices.OFFICES,
                             {offices.DEFAULT_OFFICE: bad}, clear=False):
            with self.assertRaises(SystemExit) as cm:
                offices.activate(offices.DEFAULT_OFFICE)
        self.assertIn("Resume Pushing", str(cm.exception))


class StandaloneDefault(unittest.TestCase):
    """The dangerous path is the one nobody routes through applicant_push."""

    def test_module_default_is_the_scoped_account(self):
        # `lucy rerun resume_pushing`, the --warm job and a bare `python -m` all
        # reach this module WITHOUT offices.activate(). If the default here were
        # "primary" they would sign in as the fleet reporting login, which sees
        # all 28 offices — the 2026-08-30 over-push exactly. Safe behaviour must
        # not depend on being called the right way.
        import importlib
        fresh = importlib.reload(rp)
        try:
            self.assertEqual(fresh.APPSTREAM_ACCOUNT, "lucyresume")
        finally:
            importlib.reload(rp)


class IdentityAssert(unittest.TestCase):
    def setUp(self):
        self._account = rp.APPSTREAM_ACCOUNT
        rp.APPSTREAM_ACCOUNT = "lucyresume"
        from automations.shared import creds
        self._creds = creds
        self._real = creds.appstream_account_fingerprint

    def tearDown(self):
        rp.APPSTREAM_ACCOUNT = self._account
        self._creds.appstream_account_fingerprint = self._real

    def _fingerprint(self, value):
        self._creds.appstream_account_fingerprint = lambda _n: value

    def test_matching_account_may_send(self):
        self._fingerprint(_fp("7788"))
        rp._assert_account(_Page(_console("7788")), dry_run=False)

    def test_wrong_account_may_not_send(self):
        # The wrong-screen case. This is the one that scoping cannot catch.
        self._fingerprint(_fp("7788"))
        with self.assertRaises(rp.WrongAppStreamAccount):
            rp._assert_account(_Page(_console("6039")), dry_run=False)

    def test_unrecorded_account_may_not_send(self):
        # Unknown identity is indistinguishable from the wrong one, so it is
        # refused rather than waved through. A --dry-run records it first.
        self._fingerprint(None)
        with self.assertRaises(rp.WrongAppStreamAccount):
            rp._assert_account(_Page(_console("7788")), dry_run=False)

    def test_unreadable_console_may_not_send(self):
        self._fingerprint(_fp("7788"))
        with self.assertRaises(rp.WrongAppStreamAccount):
            rp._assert_account(_Page("no identity on this page"), dry_run=False)

    def test_same_company_different_label_does_not_block(self):
        """KNOWN GAP, held deliberately. 23981 is the COMPANY and is shared by
        both Lucy logins, so the number cannot tell them apart. The label would
        — but identity() falls back to raw body text when its regex misses, and
        on Lucy 2 that produced "0 Alphalete Marketing Call Center (Account No:
        23981)   Adva". Blocking irreversible sends on text that moves would be
        an outage this guard causes. Enforced on the number, warned on the label,
        until the signed-in user can be read reliably.

        What actually bounds the push to two offices is the ACCOUNT's own
        permissions, not this."""
        self._fingerprint(_fp("23981", "Lucy Resume Pushing"))
        rp._assert_account(_Page(_console("23981", "Lucy Reports")),
                           dry_run=False)

    def test_dry_run_never_blocks(self):
        # A dry-run sends nothing, so it has nothing to protect — and it is the
        # pass that RECORDS the fingerprint a live run then asserts against.
        self._fingerprint(None)
        self.assertIsNone(rp._assert_account(_Page("nothing"), dry_run=True))


class CookiePurge(unittest.TestCase):
    def test_login_cookies_go_and_cloudflare_clearance_stays(self):
        import os
        import sqlite3
        import tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "Default"))
        db = os.path.join(d, "Default", "Cookies")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
        con.executemany("INSERT INTO cookies VALUES (?,?)", [
            (".applicantstream.com", "CFID"),
            (".applicantstream.com", "CFTOKEN"),
            (".applicantstream.com", "cf_clearance"),
            (".google.com", "SID")])
        con.commit()
        con.close()

        prev = rp.APPSTREAM_ACCOUNT
        rp.APPSTREAM_ACCOUNT = "lucyresume"
        try:
            self.assertEqual(rp._purge_appstream_session_cookies(d), 2)
        finally:
            rp.APPSTREAM_ACCOUNT = prev

        con = sqlite3.connect(db)
        left = sorted(con.execute("SELECT host_key, name FROM cookies").fetchall())
        con.close()
        # cf_clearance is Cloudflare's challenge clearance, not a login: dropping
        # it would force a fresh managed challenge on every profile seed.
        self.assertIn((".applicantstream.com", "cf_clearance"), left)
        self.assertIn((".google.com", "SID"), left)
        self.assertNotIn((".applicantstream.com", "CFID"), left)


class ConsoleCapture(unittest.TestCase):
    """The v2 dashboard has no 'Account No:' banner — the console does."""

    def setUp(self):
        self._prev = rp._OBSERVED_ACCOUNT_NO
        rp._OBSERVED_ACCOUNT_NO = None
        from automations.shared import creds
        self._creds = creds
        self._real = creds.appstream_account_fingerprint

    def tearDown(self):
        rp._OBSERVED_ACCOUNT_NO = self._prev
        self._creds.appstream_account_fingerprint = self._real

    def test_console_identity_is_used_at_send_time(self):
        # The 2026-08-31 regression: the assert read the v2 page, found nothing,
        # and a live run would have refused every send while reporting nothing
        # wrong. What the console showed has to survive to the send.
        rp._capture_account_identity(_Page(_console("7788")))
        self.assertEqual(rp._OBSERVED_ACCOUNT_NO, _fp("7788"))
        self._creds.appstream_account_fingerprint = lambda _n: _fp("7788")
        prev = rp.APPSTREAM_ACCOUNT
        rp.APPSTREAM_ACCOUNT = "lucyresume"
        try:
            rp._assert_account(_Page("v2 dashboard, no banner here"), dry_run=False)
        finally:
            rp.APPSTREAM_ACCOUNT = prev

    def test_a_console_that_shows_nothing_is_not_an_identity(self):
        rp._capture_account_identity(_Page("no banner"))
        self.assertIsNone(rp._OBSERVED_ACCOUNT_NO)


class ProfileAccountMarker(unittest.TestCase):
    """A warm profile belongs to whoever last used it."""

    def test_mismatch_forces_a_fresh_seed(self):
        # The cutover failure: the seed marker was present, so the profile was
        # reused as-is, nothing was purged, and the declared credential was
        # never used. Recorded account != declared account must re-seed.
        import os
        import tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, ".rp_account"), "w") as fh:
            fh.write("primary")
        with open(os.path.join(d, ".rp_account")) as fh:
            self.assertNotEqual(fh.read().strip(), "lucyresume")


class PerAccountSessionFile(unittest.TestCase):
    """A scoped account must not touch the primary's session file."""

    def setUp(self):
        self._prev = rp.APPSTREAM_ACCOUNT

    def tearDown(self):
        rp.APPSTREAM_ACCOUNT = self._prev

    def test_primary_uses_the_shared_file(self):
        from automations.shared import tableau_patchright as tp
        rp.APPSTREAM_ACCOUNT = "primary"
        self.assertEqual(rp._account_state_path(tp), tp.APPSTREAM_STORAGE_STATE)

    def test_scoped_account_gets_its_own_file(self):
        # Reading the shared file re-injects the BROAD login's cookies straight
        # after the profile purge, restores the console as that account and skips
        # the form login — the run then pushes as the wrong account with every
        # guard looking satisfied. Writing it would break every other AppStream
        # report on the machine. So the scoped account is isolated both ways.
        from automations.shared import tableau_patchright as tp
        rp.APPSTREAM_ACCOUNT = "lucyresume"
        path = rp._account_state_path(tp)
        self.assertNotEqual(path, tp.APPSTREAM_STORAGE_STATE)
        self.assertIn("lucyresume", path.name)
        self.assertEqual(path.parent, tp.APPSTREAM_STORAGE_STATE.parent)


class LoginFormDetection(unittest.TestCase):
    """The office switcher is not a login form."""

    class _Loc:
        def __init__(self, n): self._n = n
        def count(self): return self._n

    class _P:
        def __init__(self, searchmc=0, password=0, username=0):
            self._m = {"#searchMC": searchmc}
            self._pw, self._un = password, username
        def locator(self, sel):
            if sel in self._m:
                return LoginFormDetection._Loc(self._m[sel])
            if "password" in sel:
                return LoginFormDetection._Loc(self._pw)
            return LoginFormDetection._Loc(self._un)

    def setUp(self):
        from automations.shared import tableau_patchright as tp
        self.tp = tp

    def test_console_is_never_a_login_form(self):
        # The bug: _APPSTREAM_USERNAME_SELECTOR ends in the catch-all
        # input[type="text"], and #searchMC — the OFFICE SWITCHER — is one. So a
        # logged-in console answered "yes, there's a username field" and the
        # caller typed the username into the office search box, clicked NEXT and
        # disturbed the console the run had just established.
        page = self._P(searchmc=1, password=0, username=3)
        self.assertFalse(rp._login_form_present(page, self.tp))

    def test_console_wins_even_if_a_password_field_is_somehow_present(self):
        page = self._P(searchmc=1, password=1, username=1)
        self.assertFalse(rp._login_form_present(page, self.tp))

    def test_real_login_form_is_still_detected(self):
        page = self._P(searchmc=0, password=1, username=1)
        self.assertTrue(rp._login_form_present(page, self.tp))

    def test_username_step_of_a_two_step_form_is_detected(self):
        # The form asks for the username first and only then the password, so a
        # username field with no password field is still a real login form —
        # provided the console is not up.
        page = self._P(searchmc=0, password=0, username=1)
        self.assertTrue(rp._login_form_present(page, self.tp))

    def test_blank_page_is_not_a_login_form(self):
        page = self._P(searchmc=0, password=0, username=0)
        self.assertFalse(rp._login_form_present(page, self.tp))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class LegacyFingerprintUpgrade(unittest.TestCase):
    """A pre-label fingerprint must not lock the account out forever."""

    def setUp(self):
        from automations.shared import creds
        self.creds = creds
        self._get = creds.appstream_account_fingerprint
        self._set = creds.record_appstream_account_fingerprint
        self._acct = rp.APPSTREAM_ACCOUNT
        rp.APPSTREAM_ACCOUNT = "lucyresume"
        rp._OBSERVED_ACCOUNT_NO = None
        self.saved = []
        creds.record_appstream_account_fingerprint = (
            lambda _n, v: (self.saved.append(v), True)[1])

    def tearDown(self):
        self.creds.appstream_account_fingerprint = self._get
        self.creds.record_appstream_account_fingerprint = self._set
        rp.APPSTREAM_ACCOUNT = self._acct
        rp._OBSERVED_ACCOUNT_NO = None

    def test_bare_number_is_upgraded_to_number_and_user(self):
        # The bug: "23981" can never equal "23981/Lucy Resume Pushing", so the
        # dry-run refused to overwrite and every live send refused after it.
        self.creds.appstream_account_fingerprint = lambda _n: "23981"
        rp._assert_account(_Page(_console("23981", "Lucy Resume Pushing")),
                           dry_run=True)
        self.assertEqual(self.saved, ["23981/Lucy Resume Pushing"])

    def test_a_different_number_is_never_upgraded(self):
        # A real mismatch stays a mismatch — upgrading it would rubber-stamp
        # the wrong account.
        self.creds.appstream_account_fingerprint = lambda _n: "6039"
        rp._assert_account(_Page(_console("23981", "Lucy Resume Pushing")),
                           dry_run=True)
        self.assertEqual(self.saved, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
