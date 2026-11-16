"""Expanding a section that is already open must not close it.

Megan, 2026-11-16: "we need to know why service was only checked on some of
them." Because OwnerVille expands whichever section needs action FIRST, and
which one that is differs per rep -- Patricia Yanez's Set Status opened on
OWNER SUBMIT, the next rep's opened on SERVICE. `_expand` clicked the row
unconditionally, so a section that was already open got CLOSED, the control it
held stopped being visible, `_tick_one` timed out on it, and the save wrote
every OTHER box. One rep ends up with SERVICE done and the next does not, from
the same code on the same day.
"""
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from automations.digi_docs import ownerville as OV


class ExpandChecksBeforeItClicks(unittest.TestCase):

    def test_the_marker_is_looked_for_before_any_click(self):
        src = inspect.getsource(OV._expand)
        body = src[src.index("marker ="):]
        look = body.index("_revealed(modal, marker")
        click = body.index(".click(")
        self.assertLess(look, click,
                        "the already-open check must come before the click")

    def test_it_returns_rather_than_clicking_when_already_open(self):
        src = inspect.getsource(OV._expand)
        after = src[src.index("_revealed(modal, marker"):]
        self.assertRegex(after[:120], r"return")

    def test_the_helper_it_uses_is_the_same_one_the_retries_use(self):
        """One definition of "is it open", so the pre-check and the post-click
        wait can never disagree about it."""
        self.assertTrue(callable(OV._revealed))
        self.assertIn("_revealed", inspect.getsource(OV._expand))


class ARealAlreadyOpenSectionIsLeftAlone(unittest.TestCase):
    """The behaviour, not just the shape: a fake modal that reports the marker
    visible must come back with nothing clicked."""

    def test_no_click_happens(self):
        clicks = []

        class FakeLocator:
            def __init__(self, visible=True):
                self._visible = visible

            def wait_for(self, **kw):
                if not self._visible:
                    raise RuntimeError("not visible")

            def click(self, **kw):
                clicks.append("clicked")

            def first_(self):
                return self

            @property
            def first(self):
                return self

            def is_visible(self):
                return self._visible

            def scroll_into_view_if_needed(self, **kw):
                pass

            def locator(self, *a, **kw):
                return self

            def all_inner_texts(self):
                return []

        class FakeModal:
            def get_by_text(self, *a, **kw):
                return FakeLocator(visible=True)

            def locator(self, *a, **kw):
                return FakeLocator(visible=True)

        OV._expand(FakeModal(), "SERVICE", page=None, reveals="RES-ATT",
                   verbose=False)
        self.assertEqual(clicks, [],
                         "an already-open section must not be toggled shut")


if __name__ == "__main__":
    unittest.main()
