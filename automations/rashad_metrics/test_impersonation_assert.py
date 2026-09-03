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

# THE REAL SHAPE load_aliases() returns: {canonical_sheet_tab: [aliases]}.
# The first cut of this test encoded the opposite guess, so it passed while the
# guard was refusing the right office in production. Check the shape, do not
# assume it.
ALIASES = {"Kash Rai": ["Akashdeep Rai"],
           "Calvin Ribera": ["Calvin Rivera"]}


class _Page:
    """`label` is what beOffice reads; a LIST is one entry per read attempt, so
    a test can make the first read flake and the second succeed. `header` is
    what the page body says when the guard falls back to reading it."""

    def __init__(self, label, header=""):
        self._labels = list(label) if isinstance(label, list) else [label]
        self._header = header
        self.reads = 0
        self.url = ""

    def goto(self, url, **kw):
        self.url = url

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, _sel, **kw):
        pass

    def inner_text(self, _sel):
        return self._header

    def eval_on_selector(self, _sel, _fn):
        i = min(self.reads, len(self._labels) - 1)
        self.reads += 1
        label = self._labels[i]
        if label is None:
            raise RuntimeError("select not found")
        return label


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

    def test_a_flaky_read_is_retried_rather_than_believed(self):
        """The read that failed for Khalil answered correctly seconds later.
        One empty read is flakiness, not an answer."""
        page = _Page([None, "", "Akashdeep Rai (22177 - Palace Acquisitions, Inc.)"])
        KP.assert_impersonating(page, "RQ", "Kash Rai", ALIASES, verbose=False)
        self.assertEqual(page.reads, 3)

    def test_an_unreadable_label_raises_instead_of_passing(self):
        """2026-09-02: `/knocks Khalil Mansour` came back with Raf's 38 reps
        under the title KHALIL MANSOUR. The guard had not decided the office
        was right — the beOffice read returned empty once, and "unreadable is
        not a mismatch" waved it through. Nothing in the board said so.

        A request that errors is recoverable; a board of the wrong office's
        numbers under the right name is not, because the reader cannot tell.
        """
        page = _Page(None, header="some page with no office id in it")
        with self.assertRaises(RuntimeError) as cm:
            KP.assert_impersonating(page, "RQ", "Kash Rai", ALIASES,
                                    verbose=False)
        self.assertIn("Kash Rai", str(cm.exception))

    def test_an_unreadable_label_names_master_when_that_is_where_it_is(self):
        """The failure that actually happens: the switch didn't take, so the
        session is still Raf's office and the pull would publish his reps."""
        page = _Page(None, header=("Rafael Hidalgo - ICD • Alphalete "
                                   "Marketing, INC. (11280) Logout"))
        with self.assertRaises(RuntimeError) as cm:
            KP.assert_impersonating(page, "RQ", "Khalil Mansour", ALIASES,
                                    verbose=False)
        msg = str(cm.exception)
        self.assertIn("11280", msg)
        self.assertIn("Khalil Mansour", msg)

    def test_a_blank_label_raises_too(self):
        page = _Page("", header="")
        with self.assertRaises(RuntimeError):
            KP.assert_impersonating(page, "RQ", "Kash Rai", ALIASES,
                                    verbose=False)


if __name__ == "__main__":
    unittest.main()


class AliasShapeIsTheRealOne(unittest.TestCase):
    """Pin the shape itself, so a future reader cannot re-guess it.

    The guard's first cut iterated load_aliases() as {alias: canonical}. It is
    {canonical: [aliases]}. The set of names it would accept therefore never
    contained the alias, and it rejected the correct office in production while
    the unit test — carrying the same wrong guess — passed.
    """

    def test_load_aliases_returns_canonical_to_alias_list(self):
        import inspect
        from automations.focus_office_att import aliases as A
        sig = str(inspect.signature(A.load_aliases))
        self.assertIn("dict[str, list[str]]", sig + (A.load_aliases.__doc__ or ""),
                      "load_aliases no longer returns {canonical: [aliases]} — "
                      "assert_impersonating reads it that way")

    def test_the_guard_accepts_the_ownerville_spelling(self):
        page = _Page("Akashdeep Rai (22177 - Palace Acquisitions, Inc.)")
        KP.assert_impersonating(page, "RQ", "Kash Rai",
                                {"Kash Rai": ["Akashdeep Rai"]}, verbose=False)
