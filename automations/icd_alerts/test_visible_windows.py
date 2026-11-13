"""Lucy ECO runs in the background (Megan, 2026-11-13: "our goal should be
that they almost don't even know that Lucy is running on their machine").

A file that ships to offices and can put a window, a browser or a dialog on
the owner's screen must be listed in `visible_windows.ALLOWED` with why. A new
report that opens one fails here until somebody has written down that a
person really is needed in it -- "it was easier to debug in view" is not a
reason.
"""
import unittest

from automations.icd_alerts import visible_windows as V

# The two things that still open by themselves, in view. This set may only
# SHRINK. To add to it is to decide an owner's screen is ours to use.
STILL_OWED = {"automations/icd_alerts/ov_read.py",
              "automations/brand_audit/zoho_draft.py"}


class NothingOpensInViewWithoutAReason(unittest.TestCase):
    def setUp(self):
        self.found = V.scan()

    def test_every_window_a_shipped_file_can_open_is_listed(self):
        missing = sorted(set(self.found) - set(V.ALLOWED))
        self.assertEqual(
            missing, [],
            "these ship to offices and can open something on the owner's "
            "screen (%s). Run it hidden, or list it in visible_windows."
            "ALLOWED with why a PERSON is needed."
            % "; ".join("%s: %s" % (f, ", ".join(sorted(self.found[f])))
                        for f in missing))

    def test_the_list_holds_nothing_that_is_no_longer_true(self):
        stale = sorted(set(V.ALLOWED) - set(self.found))
        self.assertEqual(stale, [], "listed but no longer opens anything "
                                    "(or no longer ships): take it off the list")

    def test_every_entry_says_why(self):
        for f, (why, note) in V.ALLOWED.items():
            self.assertIn(why, V.WHYS, f)
            self.assertGreater(len(note.strip()), 15, f)

    def test_what_still_opens_by_itself_can_only_shrink(self):
        self.assertLessEqual(set(V.owed()), STILL_OWED)

    def test_the_scanner_sees_the_ways_a_window_gets_opened(self):
        self.assertIn("headless=False", V._marks("f(headless=False)"))
        self.assertIn("headless defaults to False",
                      V._marks("def f(a, *, headless: bool = False): pass"))
        self.assertIn("webbrowser.open", V._marks("webbrowser.open(u)"))
        self.assertIn("runs osascript",
                      V._marks("subprocess.run(['osascript', '-e', s])"))
        self.assertIn("runs open", V._marks("subprocess.run(['open', u])"))
        self.assertIn("visible-window banner",
                      V._marks("browser_banner.attach(ctx)"))
        self.assertEqual(V._marks("ctx = launch(headless=True)"), set())


if __name__ == "__main__":
    unittest.main()
