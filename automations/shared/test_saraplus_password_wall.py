"""SaraPlus's Change Password page: heal it, or wake a human — never guess.

The page is usually a STUCK CHROME PROFILE and occasionally a REAL demand
("sara asks every few weeks for a new PW update", Megan 2026-09-12), and from
inside one login they are indistinguishable. login_healing settles it the cheap
way: throw the profile away and try once more on an empty one.

Not doing that test cost a day. The page's words were read as truth about the
account, and the SaraPlus password was changed twice for a problem a 90-second
retry would have disproved.
"""
import unittest

from automations.shared import saraplus as sp

RESET_URL = "https://www.saraplus.com/e/(S(abc))/Security/ResetPassword.aspx"
GOOD_URL = "https://www.saraplus.com/e/(S(ok1))/DealerPages/Default.aspx"
RESET_TEXT = ("Change Password SARA Plus requires a reset of your SARA "
              "Password. New passwords are required to be between 8 and 15 "
              "characters")


class _Field:
    @property
    def first(self): return self
    def click(self, *a, **k): pass
    def type(self, *a, **k): pass
    def press_sequentially(self, *a, **k): pass


class _Nav:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Page:
    def __init__(self, landing, body=""):
        self.url, self._body = landing, body
    def goto(self, *a, **k): pass
    def fill(self, *a, **k): pass
    def click(self, *a, **k): pass
    def wait_for_selector(self, *a, **k): pass
    def title(self): return "SaraPlus"
    def expect_navigation(self, *a, **k): return _Nav()
    def locator(self, *a, **k): return _Field()
    def evaluate(self, script, arg=None): return self._body


class _Ctx:
    def __init__(self, page):
        self.pages, self.closed = [page], False
    def new_page(self): return self.pages[0]
    def close(self): self.closed = True


class _Playwright:
    """Hands out a scripted landing per launch, and remembers every profile
    directory it was opened on -- which is what the rotation has to change."""

    def __init__(self, landings):
        self._landings = list(landings)
        self.opened, self.contexts = [], []

    def open(self, profile_dir, headless=True):
        self.opened.append(str(profile_dir))
        url, body = self._landings.pop(0)
        ctx = _Ctx(_Page(url, body))
        self.contexts.append(ctx)
        return ctx


def _install(test, pw, rotated):
    """Swap out the two things that touch the real world."""
    test.addCleanup(setattr, sp, "open_context", sp.open_context)
    test.addCleanup(setattr, sp, "rotate_profile", sp.rotate_profile)
    sp.open_context = lambda playwright, d, headless=True: playwright.open(d, headless)
    sp.rotate_profile = lambda d, log=print: rotated.append(str(d))


def _heal(pw, rotated, test):
    _install(test, pw, rotated)
    return sp.login_healing(pw, "/tmp/profile", "who@example.com", "pw",
                            creds_hint="/tmp/creds.json", log=lambda *a: None)


class HealsAStuckProfileTest(unittest.TestCase):
    def test_a_wall_then_a_working_fresh_profile_is_healed_silently(self):
        pw = _Playwright([(RESET_URL, RESET_TEXT), (GOOD_URL, "")])
        rotated = []
        ctx, page, base = _heal(pw, rotated, self)
        self.assertEqual(base, "https://www.saraplus.com/e/(S(ok1))/")
        self.assertEqual(rotated, ["/tmp/profile"], "must rotate the stuck profile")
        self.assertEqual(len(pw.opened), 2, "must retry exactly once")

    def test_the_stuck_context_is_closed_not_leaked(self):
        pw = _Playwright([(RESET_URL, RESET_TEXT), (GOOD_URL, "")])
        _heal(pw, [], self)
        self.assertTrue(pw.contexts[0].closed, "left the stuck browser open")

    def test_a_clean_login_never_rotates_anything(self):
        pw = _Playwright([(GOOD_URL, "")])
        rotated = []
        ctx, page, base = _heal(pw, rotated, self)
        self.assertEqual(rotated, [], "threw away a perfectly good profile")
        self.assertEqual(len(pw.opened), 1)


class RealResetNeedsAHumanTest(unittest.TestCase):
    def _raise(self):
        pw = _Playwright([(RESET_URL, RESET_TEXT), (RESET_URL, RESET_TEXT)])
        with self.assertRaises(sp.SaraPasswordChangeRequired) as cm:
            _heal(pw, [], self)
        return str(cm.exception), pw

    def test_a_wall_that_survives_a_fresh_profile_is_the_real_thing(self):
        msg, pw = self._raise()
        self.assertIn("BRAND-NEW empty Chrome profile", msg)
        self.assertEqual(len(pw.opened), 2, "must have actually tried twice")

    def test_it_carries_saraplus_own_password_rules(self):
        msg, _ = self._raise()
        for rule in ("8-15 chars", "1 upper", "last 5", "3+ characters"):
            self.assertIn(rule, msg)

    def test_it_says_a_human_has_to_do_it(self):
        msg, _ = self._raise()
        self.assertIn("human has to choose", msg)
        self.assertIn("set_credentials", msg)

    def test_it_is_a_distinct_type_so_run_py_can_ping_on_it(self):
        # `except SaraError` must not swallow the one case that needs a person.
        self.assertTrue(issubclass(sp.SaraPasswordChangeRequired, sp.SaraError))
        self.assertFalse(issubclass(sp.SaraPasswordChangeRequired, sp.SaraPasswordWall))

    def test_nothing_was_read_or_written(self):
        self.assertIn("Nothing was read", self._raise()[0])


class OrdinaryFailuresAreUntouchedTest(unittest.TestCase):
    def test_a_bad_password_is_not_dressed_up_as_a_reset(self):
        pw = _Playwright([("https://ui.saraplus.com/Login.aspx", "")])
        rotated = []
        with self.assertRaises(sp.SaraError) as cm:
            _heal(pw, rotated, self)
        self.assertIn("still on the login page", str(cm.exception))
        self.assertNotIsInstance(cm.exception, sp.SaraPasswordChangeRequired)
        self.assertEqual(rotated, [], "rotated a profile over a wrong password")


if __name__ == "__main__":
    unittest.main()
