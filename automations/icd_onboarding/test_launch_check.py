"""The launch check must not be able to pass an office by papering over it."""
import inspect
import unittest

from automations.icd_onboarding import launch_check as LC


class ReadOnly(unittest.TestCase):
    def test_nothing_in_here_writes(self):
        """It runs on a day when the answers are cheap, which is only true
        while it costs nothing to run. A check that fills a blank in to go
        green is worse than no check -- Alphalete's $10.00 on somebody else's
        payroll record is the error nobody would see."""
        src = inspect.getsource(LC)
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        for forbidden in ("batch_update", "ws.update", "ensure_columns(",
                          "--write", "send(", "click("):
            self.assertNotIn(forbidden, code, forbidden)

    def test_every_check_says_what_breaks_and_how_to_fix_it(self):
        """A red line nobody can act on gets ignored, and then the whole
        check gets ignored."""
        class Fake:
            pass
        for fn in LC.CHECKS:
            sig = inspect.signature(fn)
            self.assertEqual(list(sig.parameters), ["office_key"]
                             if "office_key" in sig.parameters else ["key"],
                             fn.__name__)

    def test_a_failing_check_never_fails_the_run(self):
        """One unanswerable question must not hide the other six."""
        src = inspect.getsource(LC.run)
        self.assertIn("except Exception", src)


class BlueInkAccount(unittest.TestCase):
    """The one check where a PASS can be the dangerous answer."""

    def test_an_icd_falling_back_to_the_repo_key_is_not_a_pass(self):
        """It would send that office's new starts their documents out of
        Alphalete's Blue Ink account -- and the send SUCCEEDS, so nothing
        else would ever report it."""
        src = inspect.getsource(LC.check_blueink)
        self.assertIn("is_alphalete", src)
        self.assertIn("theirs or (is_alphalete and repo)", src)


class ExitCode(unittest.TestCase):
    def test_zero_only_when_everything_passed(self):
        src = inspect.getsource(LC.main)
        self.assertIn("all(c.ok for c in got)", src)


if __name__ == "__main__":
    unittest.main()
