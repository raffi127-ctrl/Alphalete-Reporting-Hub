"""Every wait on View Progress survives the page reloading under it.

2026-11-16: eight of Raf's owner submits died in one evening on
"TimeoutError ... waiting for navigation to finish". Not one of them was about
the rep, the confirm box or the service radio -- the page simply had not
finished loading. Changing campaign and Show All each reload the WHOLE View
Progress page ("&showViewRange=0"), and on a big office that reload outlasts a
20-second wait.

The rule these pin: anything waiting for an element on that page waits for the
LOAD EVENT first, and then waits long. networkidle is never the answer --
OwnerVille keeps a background connection open and never reaches it, so a
networkidle wait burns its whole timeout and carries on regardless.
"""
from __future__ import annotations

import inspect
import re
import unittest

from automations.headshots import ov_upload as U


def src_of(fn) -> str:
    return inspect.getsource(fn)


class TheHeavyPageWaitsAreLongAndLoadAware(unittest.TestCase):

    def test_the_search_box_waits_for_the_load_first(self):
        s = src_of(U._search_box)
        self.assertIn("_wait_loaded(page)", s)
        self.assertLess(s.index("_wait_loaded(page)"), s.index("wait_for("))

    def test_the_campaign_select_waits_for_the_load_first(self):
        s = src_of(U._campaign_select)
        self.assertIn("_wait_loaded(page)", s)
        self.assertLess(s.index("_wait_loaded(page)"), s.index("wait_for("))

    def test_neither_still_uses_a_twenty_second_wait(self):
        """20s is shorter than the reload it is waiting on."""
        for fn in (U._search_box, U._campaign_select):
            with self.subTest(fn=fn.__name__):
                for ms in re.findall(r"timeout=(\d+)", src_of(fn)):
                    self.assertGreaterEqual(int(ms), 60000)


class NothingWaitsOnNetworkidle(unittest.TestCase):
    """OwnerVille never reaches it, so it is always a timeout dressed up as a
    wait -- the full default spent before carrying on anyway."""

    def test_find_rep_waits_on_the_load_event(self):
        s = src_of(U.find_rep)
        self.assertNotIn('wait_for_load_state("networkidle")', s)

    def test_wait_loaded_itself_asks_for_load_not_networkidle(self):
        """Its docstring says why networkidle is wrong, so the prose is
        stripped before asserting on the code
        ([[reference_source_assertions_strip_prose]])."""
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(src_of(U._wait_loaded)))
        fn = tree.body[0]
        if (fn.body and isinstance(fn.body[0], ast.Expr)
                and isinstance(fn.body[0].value, ast.Constant)):
            fn.body.pop(0)
        s = ast.unparse(tree)
        self.assertIn("'load'", s)
        self.assertNotIn("networkidle", s)

    def test_a_failure_to_load_is_not_fatal(self):
        """A slow page is a slow page; the element waits below are the real
        gate and they must get their chance."""
        self.assertIn("except", src_of(U._wait_loaded))


class ShowAllClicksOnce(unittest.TestCase):
    """The radio RELOADS the page, so a retry loop restarts the slow load it
    was waiting for -- which is how one stall became eight."""

    def test_one_click_no_wait_after(self):
        s = src_of(U._show_all)
        self.assertIn("no_wait_after=True", s)


if __name__ == "__main__":
    unittest.main()
