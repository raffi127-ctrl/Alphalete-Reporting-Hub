"""Blue Ink and the onboarding-documents question are asked in the Sterling / background-check setup, never in
the main ECO install (Megan, 2026-11-13: "the main eco installer shouldn't ask for
blue ink - that's for a sterling/bg enrollment anyways")."""
import inspect
import unittest

from automations.icd_alerts import finish_setup as FS
from automations.icd_alerts import sterling_setup as SS


class BlueInkLivesInTheSterlingSetup(unittest.TestCase):
    def test_main_install_has_no_blue_ink_step(self):
        src = inspect.getsource(FS.run)
        steps = src.split("steps: List = [", 1)[1].split("]", 1)[0]
        self.assertNotIn("Blue Ink", steps)
        self.assertNotIn("Onboarding documents", steps)
        self.assertFalse(hasattr(FS, "_blueink"))
        self.assertFalse(hasattr(FS, "_digi_docs"))

    def test_sterling_setup_asks_it_after_a_good_sign_in(self):
        src = inspect.getsource(SS.main)
        self.assertIn("blueink_step(say)", src)
        self.assertIn("digi_docs_step(office_key, say)", src)

    def test_a_copy_without_the_blue_ink_files_shows_no_error(self):
        import builtins
        real = builtins.__import__

        def fake(name, globals=None, locals=None, fromlist=(), level=0):
            if any(m in name or m in (fromlist or ())
                   for m in ("blueink_setup", "digi_docs_setup")):
                raise ImportError("not shipped")
            return real(name, globals, locals, fromlist, level)

        builtins.__import__ = fake
        try:
            said = [SS.blueink_step(say=lambda *_: None),
                    SS.digi_docs_step("some-office", say=lambda *_: None)]
        finally:
            builtins.__import__ = real
        self.assertEqual(said, ["nothing to do yet", "nothing to do yet"])


if __name__ == "__main__":
    unittest.main()
