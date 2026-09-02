"""Prove the session switched office before believing a single number.

`_find_owner_and_impersonate` returning "ok" only means confirmImpersonate was
CALLED. Ownerville hands an impersonated session the same rqst as master, so a
switch that silently fails leaves every later fetch answering for the wrong
office with nothing raising.

Both failures on 2026-09-01 were this:
  * `/knocks Kash Rai` returned Calvin Ribera's seven Energy Wells reps under
    the heading "TOTAL KNOCKS — KASH RAI".
  * Jay Turnage's board carried Raf's 37 reps into the Energy Wells chat.

A board with the right title and another office's numbers is worse than no
board — unlike a blank one, the reader cannot tell.

Offline: the page is a stub returning a canned beOffice label.
"""
import unittest

from automations.rashad_metrics import knocks_pull as KP

# alias -> canonical, the shape load_aliases returns.
ALIASES = {"Akashdeep Rai": "Kash Rai", "Calvin Rivera": "Calvin Ribera"}


class _Page:
    def __init__(self, label):
        self._label = label
        self.url = ""

    def goto(self, url, **kw):
        self.url = url

    def wait_for_timeout(self, _ms):
        pass

    def eval_on_selector(self, _sel, _fn):
        if self._label is None:
            raise RuntimeError("select not found")
        return self._label


class AssertImpersonating(unittest.TestCase):
    def test_the_right_office_passes(self):
        page = _Page("Calvin Ribera (22162 - Vernon, Inc.)")
        KP.assert_impersonating(page, "RQ", "Calvin Ribera", ALIASES,
                                verbose=False)

    def test_the_ownerville_spelling_passes_via_the_alias(self):
        """The sheet's canonical is 'Kash Rai'; ownerville says 'Akashdeep
        Rai'. That is a match, not a mismatch."""
        page = _Page("Akashdeep Rai (22177 - Palace Acquisitions, Inc.)")
        KP.assert_impersonating(page, "RQ", "Kash Rai", ALIASES,
                                verbose=False)

    def test_another_office_raises(self):
        """The exact Kash-Rai-shows-Calvin's-reps bug."""
        page = _Page("Calvin Ribera (22162 - Vernon, Inc.)")
        with self.assertRaises(RuntimeError) as cm:
            KP.assert_impersonating(page, "RQ", "Kash Rai", ALIASES,
                                    verbose=False)
        msg = str(cm.exception)
        self.assertIn("Calvin Ribera", msg)
        self.assertIn("Kash Rai", msg)

    def test_an_unreadable_label_is_not_a_mismatch(self):
        """A check that fails closed on its own flakiness would take every
        board down for a reason that is not real."""
        KP.assert_impersonating(_Page(None), "RQ", "Kash Rai", ALIASES,
                                verbose=False)

    def test_a_blank_label_is_not_a_mismatch(self):
        KP.assert_impersonating(_Page(""), "RQ", "Kash Rai", ALIASES,
                                verbose=False)


if __name__ == "__main__":
    unittest.main()
