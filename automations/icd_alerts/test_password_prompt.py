"""A refused password pops the password box on the office Mac, not the
browser sign-in (Khalil, 2026-09-22/23)."""
import inspect
import unittest

from automations.icd_alerts import autoprompt as AP, run as R


class PasswordPromptTest(unittest.TestCase):
    def test_the_password_system_runs_set_login(self):
        spec = AP.SYSTEMS["saraplus_password"]
        self.assertEqual(spec["module"], "automations.icd_alerts.run")
        self.assertEqual(spec["args"], ["--set-login"])

    def test_a_refused_password_picks_the_box(self):
        src = inspect.getsource(R.cmd_once)
        self.assertIn('"saraplus_password" if "did not accept" in str(e) else "saraplus"', src)

    def test_a_good_new_password_clears_the_hold(self):
        src = inspect.getsource(R.cmd_set_login)
        self.assertLess(src.index("clear_sara_hold()"), src.index("That worked"))


if __name__ == "__main__":
    unittest.main()
