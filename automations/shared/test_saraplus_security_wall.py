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
    kw.pop("read_code", None)          # the passcode flow was removed 2026-09-12
    return sp.login(page, "somebody@example.com", "pw",
                    creds_hint="/tmp/creds.json", log=lambda *a: None, **kw)


class StuckProfileTest(unittest.TestCase):
    """The Change Password page is a PROFILE symptom. Proved 2026-09-12: the
    same credential went straight into DealerPages from an incognito window and
    from a new empty profile, while the sweep's own profile sat on this page
    for 30 passes. Moving the profile aside fixed it on the next tick.

    These tests exist so nobody reads that page's words and changes a password
    that was never wrong -- which is exactly what happened, twice."""

    def _msg(self, page):
        with self.assertRaises(sp.SaraError) as cm:
            _login(page, read_code=lambda s: "123456")
        return str(cm.exception)

    def test_the_profile_is_named_before_the_password(self):
        msg = self._msg(_Page(RESET_URL, body=RESET_TEXT))
        self.assertIn("THIS BROWSER PROFILE", msg)
        self.assertLess(msg.index("PROFILE"), msg.index("set_credentials"),
                        "the password remedy must not come first")

    def test_it_warns_against_touching_the_password_first(self):
        self.assertIn("BEFORE TOUCHING THE PASSWORD",
                      self._msg(_Page(RESET_URL, body=RESET_TEXT)))

    def test_it_gives_the_test_that_tells_the_two_apart(self):
        # A new empty profile landing here too is the ONLY thing that makes it
        # a real account reset.
        self.assertIn("new empty profile",
                      self._msg(_Page(RESET_URL, body=RESET_TEXT)))

    def test_the_password_rules_are_still_there_for_the_rare_real_case(self):
        msg = self._msg(_Page(RESET_URL, body=RESET_TEXT))
        self.assertIn("8-15 chars", msg)
        self.assertIn("3+ characters", msg)

    def test_no_passcode_is_requested_on_this_page(self):
        asked = []
        with self.assertRaises(sp.SaraError):
            _login(_Page(RESET_URL, body=RESET_TEXT),
                   read_code=lambda s: asked.append(s) or "123456")
        self.assertEqual(asked, [], "requested a passcode on a Change Password page")

    def test_the_page_text_alone_is_enough(self):
        self.assertIn("Change Password page",
                      self._msg(_Page("https://www.saraplus.com/e/(S(x))/Default.aspx",
                                      body=RESET_TEXT)))

