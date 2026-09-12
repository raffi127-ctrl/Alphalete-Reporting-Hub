"""A /Security/ landing is the PASSCODE WALL, not a password problem.

2026-09-12, and it took three readings to get right. The sales board sweep
('Sales Text Updates') failed three passes in a row and the channel got only

    SaraError: logged in but landed somewhere unexpected:
    https://www.saraplus.com/e/(S(...))/Security/ResetPassword.aspx

Read #1: "SaraPlus moved a page" -- wrong, it had not.
Read #2: "the password expired" -- wrong, Megan confirmed nothing changed.
Read #3, and the right one: the session id in that url means the PASSWORD WAS
ACCEPTED, and /Security/ is where SaraPlus puts a browser it does not
recognise until an emailed passcode clears. rc_contact_sync met this same wall
on the B2B account on 2026-09-03; the shared login had no answer for it.

These tests pin all three: that the wall is named, that a wired-up login walks
through it, and that nobody is ever again told to change a good password.
"""
import unittest

from automations.shared import saraplus as sp

# The PASSCODE wall and the PASSWORD-RESET wall both live under /Security/.
WALL_URL = "https://www.saraplus.com/e/(S(ujsu4nwkbwvzfsicqn3xd00l))/Security/VerifyPasscode.aspx"
RESET_URL = "https://www.saraplus.com/e/(S(ujsu4nwkbwvzfsicqn3xd00l))/Security/ResetPassword.aspx"
RESET_TEXT = ("Change Password SARA Plus requires a reset of your SARA "
              "Password. New passwords are required to be between 8 and 15 characters")
HUB_URL = "https://www.saraplus.com/e/(S(abc123))/Reports/ReportingHub.aspx"
DEALER_URL = "https://www.saraplus.com/e/(S(abc123))/DealerPages/Default.aspx"


class _Field:
    @property
    def first(self): return self
    def click(self, *a, **k): pass
    def type(self, *a, **k): pass


class _Nav:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Page:
    """The smallest page that walks _login. `after_code` is where it lands
    once a code has been typed in -- that is the whole point of the wall."""

    def __init__(self, landing, body="", after_code=None, code_field="txtCode"):
        self.url = landing
        self._body = body
        self._after = after_code
        self._code_field = code_field
        self.typed = []
        self.keyboard = self

    def goto(self, *a, **k): pass
    def fill(self, *a, **k): pass
    def click(self, *a, **k): pass
    def wait_for_selector(self, *a, **k): pass
    def wait_for_timeout(self, *a, **k): pass
    def wait_for_load_state(self, *a, **k): pass
    def title(self): return "SaraPlus"
    def expect_navigation(self, *a, **k): return _Nav()
    def locator(self, *a, **k): return _Field()

    def press(self, *a, **k):
        if self._after:
            self.url = self._after

    def evaluate(self, script, arg=None):
        # The handful of probes _login's passcode path makes, answered by
        # shape rather than by running the real JS.
        if "document.body.innerText" in script and "querySelectorAll" not in script:
            return self._body
        if "emailradio" in script.lower():
            return "MainContent_rbEmailRadio"
        if "rcbList" in script:
            return "reports@example.com"
        if "getcodeemail" in script.lower():
            return "Get Code [MainContent_btnGetCodeEmail]"
        if "typable" in script:
            return self._code_field
        if "type !== 'hidden'" in script:
            return {"id": "rcbEmailOptions_Input", "value": "reports@example.com"}
        return None


def _login(page, **kw):
    return sp.login(page, "somebody@example.com", "pw",
                    creds_hint="/tmp/creds.json", log=lambda *a: None, **kw)


class WallIsNamedTest(unittest.TestCase):
    """With no code reader wired, the error has to say what this is."""

    def _msg(self, url=WALL_URL):
        with self.assertRaises(sp.SaraError) as cm:
            _login(_Page(url))
        return str(cm.exception)

    def test_it_is_called_a_browser_challenge(self):
        self.assertIn("CHALLENGING THIS BROWSER", self._msg())

    def test_it_does_not_blame_the_password(self):
        # The whole cost of 2026-09-12: two wrong reads, both about passwords.
        msg = self._msg()
        self.assertIn("NOT an expired password", msg)
        self.assertNotIn("somewhere unexpected", msg)

    def test_it_names_the_account_and_both_ways_out(self):
        msg = self._msg()
        self.assertIn("somebody@example.com", msg)
        self.assertIn("read_code", msg)          # the unattended fix
        self.assertIn("by hand", msg)            # the one-time manual fix

    def test_nothing_was_read_or_written(self):
        self.assertIn("Nothing was read", self._msg())

    def test_the_picker_page_counts_as_the_wall_too(self):
        # The first screen is a destination picker whose URL need not say
        # 'Security' -- its words are the signal there.
        msg = self._msg("https://www.saraplus.com/e/(S(x))/Default.aspx")
        # no wall words in the body -> falls through to the old error
        self.assertIn("somewhere unexpected", msg)
        with self.assertRaises(sp.SaraError) as cm:
            _login(_Page("https://www.saraplus.com/e/(S(x))/Default.aspx",
                         body="It appears that this is a new location or browser"))
        self.assertIn("CHALLENGING THIS BROWSER", str(cm.exception))


class WallIsClearedTest(unittest.TestCase):
    """With a reader wired, the sweep walks through instead of dying."""

    def test_a_challenged_login_clears_and_returns_the_dealer_root(self):
        seen = []
        page = _Page(WALL_URL, after_code=HUB_URL)
        base = _login(page, read_code=lambda since: seen.append(since) or "123456")
        self.assertEqual(base, "https://www.saraplus.com/e/(S(abc123))/")
        self.assertEqual(len(seen), 1, "should have asked for exactly one code")

    def test_the_code_reader_is_asked_for_a_FRESH_code(self):
        # `since` is stamped before the request, a little early, so a code
        # discarded for being a second too old cannot look like one that
        # never arrived.
        import datetime as dt
        got = {}
        page = _Page(WALL_URL, after_code=HUB_URL)
        _login(page, read_code=lambda since: got.setdefault("since", since) or "123456")
        age = dt.datetime.now().astimezone() - got["since"]
        self.assertGreaterEqual(age.total_seconds(), 30)
        self.assertLess(age.total_seconds(), 120)

    def test_a_wall_that_never_clears_is_not_reported_as_a_password(self):
        page = _Page(WALL_URL, after_code=WALL_URL)       # code never sticks
        with self.assertRaises(sp.SaraError) as cm:
            _login(page, read_code=lambda since: "123456")
        msg = str(cm.exception)
        self.assertIn("would not accept a verification code", msg)
        self.assertIn("not a stale-code problem", msg)

    def test_no_code_box_says_so_instead_of_typing_into_a_button(self):
        page = _Page(WALL_URL, after_code=HUB_URL, code_field=None)
        with self.assertRaises(sp.SaraError) as cm:
            _login(page, read_code=lambda since: "123456")
        self.assertIn("no box to type it into", str(cm.exception))


class OrdinaryLoginsTest(unittest.TestCase):
    """The path 99% of sweeps take must be untouched."""

    def test_a_remembered_browser_still_lands_on_dealerpages(self):
        self.assertEqual(_login(_Page(DEALER_URL)),
                         "https://www.saraplus.com/e/(S(abc123))/")

    def test_a_reader_is_never_consulted_when_there_is_no_wall(self):
        called = []
        base = _login(_Page(DEALER_URL), read_code=lambda s: called.append(s))
        self.assertEqual(called, [], "asked for a code with no challenge on screen")
        self.assertEqual(base, "https://www.saraplus.com/e/(S(abc123))/")

    def test_landing_straight_on_the_hub_is_a_success_not_a_surprise(self):
        # rc_contact_sync learned this on 2026-09-03: a just-verified login
        # lands on Reports/, and calling that 'unexpected' throws away a
        # login that had in fact just succeeded.
        self.assertEqual(_login(_Page(HUB_URL)),
                         "https://www.saraplus.com/e/(S(abc123))/")

    def test_a_bounce_back_to_the_login_page_still_blames_the_credentials(self):
        with self.assertRaises(sp.SaraError) as cm:
            _login(_Page("https://ui.saraplus.com/Login.aspx"))
        self.assertIn("still on the login page", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class PasscodeInboxTest(unittest.TestCase):
    """SaraPlus mails THIS account's code to alphaletemarketing@gmail.com, not
    the reporting inbox — so the reader must be able to look in either, and
    must say so plainly when it can look in neither (Megan 2026-09-12)."""

    def test_the_reader_can_be_pointed_at_another_mailbox(self):
        import inspect
        from automations.rc_contact_sync import verify_code as VC
        self.assertIn("inbox", inspect.signature(VC.wait_for_code).parameters)

    def test_a_missing_app_password_names_both_ways_out(self):
        from automations.rc_contact_sync import verify_code as VC
        with self.assertRaises(VC.CodeNotFound) as cm:
            VC._inbox(("someone@example.com", "/nope/not/here"))
        msg = str(cm.exception)
        self.assertIn("forward", msg.lower())          # the proven route
        self.assertIn("app password", msg.lower())     # the other one
        self.assertIn("someone@example.com", msg)

    def test_the_default_inbox_is_still_the_reporting_account(self):
        from automations.rc_contact_sync import verify_code as VC
        from automations.shared import email_ingest as _ing
        self.assertIsNone(VC.DEFAULT_INBOX)
        self.assertEqual(_ing.ACCOUNT, "alphaletereporting@gmail.com")

    def test_the_sales_board_knows_which_account_saraplus_mails(self):
        from automations.alphalete_sales_board import config as C
        self.assertEqual(C.SARA_ACCOUNT, "alphaletemarketing@gmail.com")
        self.assertEqual(C.PASSCODE_INBOX[0], C.SARA_ACCOUNT)



class PasswordResetTest(unittest.TestCase):
    """The OTHER /Security/ wall. Read off the live page 2026-09-12 after the
    passcode flow ran into it and reported 'no EMAIL destination' — there is no
    picker on a Change Password page, so the sweep has to stop here instead."""

    def _msg(self, page):
        with self.assertRaises(sp.SaraError) as cm:
            _login(page, read_code=lambda s: "123456")
        return str(cm.exception)

    def test_the_reset_page_is_not_mistaken_for_the_passcode_wall(self):
        msg = self._msg(_Page(RESET_URL, body=RESET_TEXT))
        self.assertIn("FORCING A PASSWORD CHANGE", msg)
        self.assertNotIn("EMAIL destination", msg)

    def test_it_says_both_things_are_true_at_once(self):
        # The exact confusion that cost 2026-09-12: nobody changed the
        # password AND SaraPlus is demanding a change.
        self.assertIn("NOBODY CHANGED IT", self._msg(_Page(RESET_URL, body=RESET_TEXT)))

    def test_it_carries_the_rule_a_human_needs(self):
        msg = self._msg(_Page(RESET_URL, body=RESET_TEXT))
        self.assertIn("8-15 characters", msg)     # SaraPlus's own rule
        self.assertIn("set_credentials", msg)     # what to run after
        self.assertIn("needs a human", msg)

    def test_the_code_reader_is_never_asked_on_a_reset_page(self):
        asked = []
        with self.assertRaises(sp.SaraError):
            _login(_Page(RESET_URL, body=RESET_TEXT),
                   read_code=lambda s: asked.append(s) or "123456")
        self.assertEqual(asked, [], "requested a passcode for a password reset")

    def test_the_page_text_alone_is_enough(self):
        # Belt and braces: if SaraPlus renames the .aspx, its own words still
        # identify it. The URL here is an ordinary one.
        msg = self._msg(_Page("https://www.saraplus.com/e/(S(x))/Default.aspx",
                              body=RESET_TEXT))
        self.assertIn("FORCING A PASSWORD CHANGE", msg)

    def test_a_real_passcode_wall_still_clears(self):
        # The reset check must not swallow the challenge it sits next to.
        page = _Page(WALL_URL, after_code=HUB_URL)
        self.assertEqual(_login(page, read_code=lambda s: "123456"),
                         "https://www.saraplus.com/e/(S(abc123))/")
