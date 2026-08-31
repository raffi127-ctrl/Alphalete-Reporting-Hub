"""DRUG TEST would not open, and one strategy was never going to be enough.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.digi_docs.test_force_expand

WHY (Megan 2026-08-31, "fix the drug test"). BACKGROUND CHECK opened on the
first strategy all morning; DRUG TEST opened on none of them. The log said the
same three lines for every rep in two runs:

    (DRUG TEST: the row itself wasn't clickable)
    (DRUG TEST: label click didn't reveal — trying the chevron)
    (DRUG TEST: still not expanded)

so nobody's attestation boxes were ticked. Guessing which single element is the
real toggle had already failed three times, so _force_expand stops guessing and
works through the plausible ones — real click, JS click (which ignores the
overlay/pointer-events that make a visible element "unclickable"), the
clickable children, and <details> — checking after each whether the section
actually opened.

The checking-after-each is the point. An expander that clicks and assumes is
how this looked fine while ticking nothing.
"""
from __future__ import annotations

import unittest

from automations.digi_docs import ownerville as ov


class _El:
    """One candidate row. `opens_on` names the single thing that works."""

    def __init__(self, state, opens_on=None, kids=None, clickable=False):
        self.state, self.opens_on = state, opens_on
        self._kids, self.clickable = kids or {}, clickable

    def click(self, timeout=0, force=False):
        if not (self.clickable or force):
            raise RuntimeError("not clickable")
        if self.opens_on in ("force click", "click"):
            self.state["open"] = True

    def evaluate(self, script):
        if "details" in script:
            if self.opens_on == "details":
                self.state["open"] = True
            return None
        if self.opens_on == "js click":
            self.state["open"] = True
        return None

    def locator(self, sel):
        return self._kids.get(sel.strip("[]'role=") if sel.startswith("[")
                              else sel, _Empty())


class _Empty:
    def count(self):
        return 0

    def nth(self, i):
        raise IndexError


class _Kid:
    def __init__(self, state, opens=False):
        self.state, self.opens = state, opens

    def count(self):
        return 1

    def nth(self, i):
        return self

    def evaluate(self, script):
        if self.opens:
            self.state["open"] = True


class _Modal:
    def __init__(self, state, rows):
        self.state, self._rows = state, rows

    def get_by_text(self, marker, exact=False):
        state = self.state

        class _M:
            @property
            def first(s):
                return s

            def wait_for(s, state_=None, timeout=0, **kw):
                if not state["open"]:
                    raise RuntimeError("not visible")
        return _M()


class ForceExpandTest(unittest.TestCase):

    def _run(self, row_factory):
        state = {"open": False}
        rows = [row_factory(state)]
        modal = _Modal(state, rows)
        ov._status_rows = lambda m, l: rows          # patched for the test
        return ov._force_expand(modal, "DRUG TEST", "requires a passing",
                                verbose=False), state

    def setUp(self):
        self._real = ov._status_rows
        self.addCleanup(setattr, ov, "_status_rows", self._real)

    def test_a_row_that_only_answers_a_js_click_still_opens(self):
        """The real DRUG TEST symptom: visible, but a normal click is refused."""
        ok, state = self._run(lambda st: _El(st, opens_on="js click"))
        self.assertTrue(ok)
        self.assertTrue(state["open"])

    def test_a_row_that_only_answers_a_forced_click_still_opens(self):
        ok, state = self._run(lambda st: _El(st, opens_on="force click"))
        self.assertTrue(ok)

    def test_a_details_section_opens_by_attribute(self):
        ok, state = self._run(lambda st: _El(st, opens_on="details"))
        self.assertTrue(ok)

    def test_a_child_button_carrying_the_toggle_opens_it(self):
        ok, _ = self._run(
            lambda st: _El(st, kids={"button": _Kid(st, opens=True)}))
        self.assertTrue(ok)

    def test_a_section_nothing_opens_reports_false_rather_than_pretending(self):
        ok, state = self._run(lambda st: _El(st))
        self.assertFalse(ok)
        self.assertFalse(state["open"])


if __name__ == "__main__":
    unittest.main()
