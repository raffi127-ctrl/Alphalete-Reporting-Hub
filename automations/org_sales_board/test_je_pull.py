"""Tests for je_pull's 'Sales Week Ending' selection.

WHY A FAKE VIZ: the selection logic is the part that broke (2026-08-16 — the
Sunday board-catchup dropped Retail JE with box='(Multiple values)'), and it
cannot be exercised anywhere else: driving the real view needs a warm
ownerville session, which only the mini has (a laptop run hits Cloudflare).
So the Tableau categorical quick filter is modelled here — its tri-state
'(All)' row, its refusal to be left with nothing selected, and the other
filter cards that render their own options into the same viz, and a cover
over the combobox that intercepts the click that opens it (2026-09-20) — and
the driver is run against it.

Run:  .venv/bin/python -m pytest automations/org_sales_board/test_je_pull.py
  or  .venv/bin/python -m unittest automations.org_sales_board.test_je_pull
"""
from __future__ import annotations

import re
import unittest

from automations.org_sales_board import je_pull


# --------------------------------------------------------------- fake viz

class _Item:
    """One `div.FIItem[role=checkbox]` row."""

    def __init__(self, filt, text):
        self.filt = filt
        self.text = text

    # -- Playwright surface -------------------------------------------------
    def inner_text(self):
        return self.text

    def get_attribute(self, name):
        if name != "aria-checked":
            return None
        return "true" if self.filt.is_checked(self.text) else "false"

    def scroll_into_view_if_needed(self, **_kw):
        pass

    def hover(self, **_kw):
        self.filt.hovered = self.text

    def locator(self, selector):
        if ".FICheckRadio" in selector:
            return _Loc([_Glyph(self)])
        if "a, button, span" in selector:      # the hover-revealed 'Only' link
            if self.filt.has_only_link and self.filt.hovered == self.text:
                return _Loc([_OnlyLink(self)])
            return _Loc([])
        return _Loc([])


class _Glyph:
    def __init__(self, item):
        self.item = item

    def scroll_into_view_if_needed(self, **_kw):
        pass

    def click(self, **_kw):
        self.item.filt.toggle(self.item.text)


class _OnlyLink:
    def __init__(self, item):
        self.item = item

    def inner_text(self):
        return "Only"

    def count(self):
        return 1        # `.first` is itself a Locator in Playwright

    def click(self, **_kw):
        self.item.filt.only(self.item.text)


class _Combo:
    """The 'Sales Week Ending' combobox.

    State lives on the filter, not here: `locator()` builds a fresh _Combo on
    every call, so a counter on the instance would reset between passes.
    """

    def __init__(self, filt):
        self.filt = filt

    def inner_text(self):
        return self.filt.box_text()

    def click(self, **kw):
        self.filt.combo_clicks += 1
        self.filt.combo_click_kwargs.append(kw)
        if self.filt.combo_fails:
            # What a cover over the combobox actually does: the click is
            # INTERCEPTED, not refused, so Playwright waits out its timeout
            # and raises. Verbatim shape of the 2026-09-20 board failure.
            self.filt.combo_fails -= 1
            raise TimeoutError(
                "Locator.click: Timeout 30000ms exceeded. "
                "<div class='tab-glass'> intercepts pointer events")
        self.filt.open = True


class _Loc:
    """A Playwright Locator over a fixed list of fake elements."""

    def __init__(self, els):
        self.els = list(els)

    def count(self):
        return len(self.els)

    def nth(self, i):
        return self.els[i]

    @property
    def first(self):
        return self.els[0] if self.els else _Missing()

    def filter(self, has_text=None):
        if has_text is None:
            return self
        keep = [e for e in self.els
                if has_text.search(e.inner_text() or "")]
        return _Loc(keep)


class _Missing:
    """`.first` on an empty locator — every call is a miss, never a crash."""

    def count(self):
        return 0

    def inner_text(self):
        return ""

    def get_attribute(self, _name):
        return None

    def scroll_into_view_if_needed(self, **_kw):
        pass

    def hover(self, **_kw):
        pass

    def click(self, **_kw):
        raise AssertionError("clicked an element that does not exist")

    def locator(self, _selector):
        return _Loc([])


class FakeFilter:
    """A Tableau 'Sales Week Ending' quick filter.

    weeks           every option, newest last
    checked         which are ticked to start
    has_only_link   does this Tableau render the per-row 'Only' link
    other_options   options belonging to a DIFFERENT filter card that renders
                    into the same viz — always ticked, must never be touched
    """

    def __init__(self, weeks, checked, has_only_link=False, other_options=(),
                 combo_fails=0):
        self.weeks = list(weeks)
        self.checked = set(checked)
        self.has_only_link = has_only_link
        self.other = {o: True for o in other_options}
        self.open = False
        self.hovered = None
        self.clicks = 0
        self.combo_fails = combo_fails    # how many opens get intercepted
        self.combo_clicks = 0
        self.combo_click_kwargs = []

    # -- the filter's own behaviour ----------------------------------------
    def is_checked(self, text):
        if text == "(All)":
            return len(self.checked) == len(self.weeks)
        if text in self.other:
            return self.other[text]
        return text in self.checked

    def toggle(self, text):
        self.clicks += 1
        if text == "(All)":
            # Tri-state row: anything short of everything selects everything.
            self.checked = set(self.weeks)
            return
        if text in self.other:
            self.other[text] = not self.other[text]
            return
        if text in self.checked:
            self.checked.discard(text)
        else:
            self.checked.add(text)
        if not self.checked:
            # Tableau will not leave a categorical filter empty — it reverts to
            # everything. This is what made the old blind-toggle loop thrash.
            self.checked = set(self.weeks)

    def only(self, text):
        self.clicks += 1
        self.checked = {text}

    def box_text(self):
        if len(self.checked) == len(self.weeks):
            return "(All)"
        if len(self.checked) == 1:
            return next(iter(self.checked))
        return "(Multiple values)"

    # -- Playwright surface -------------------------------------------------
    def locator(self, selector):
        if "tabComboBox" in selector:
            return _Loc([_Combo(self)])
        if "FIItem" in selector:
            if not self.open:
                return _Loc([])          # a closed menu renders no options
            rows = [_Item(self, "(All)")]
            rows += [_Item(self, w) for w in self.weeks]
            rows += [_Item(self, o) for o in self.other]   # other filter card
            if "aria-checked=" in selector:
                want = re.search(r'aria-checked="([^"]+)"', selector).group(1)
                rows = [r for r in rows
                        if r.get_attribute("aria-checked") == want]
            return _Loc(rows)
        if "tab-glass" in selector:
            return _Loc([])
        return _Loc([])


class FakePage:
    def __init__(self, filt):
        self.filt = filt
        self.keyboard = self

    def wait_for_timeout(self, _ms):
        pass

    def press(self, _key):
        self.filt.open = False           # Escape collapses the menu


WEEKS = ["7/26/2026", "8/2/2026", "8/9/2026", "8/16/2026"]
TARGET = "8/16/2026"


def _drive(filt, verbose=False):
    je_pull._drive_week_selection(TARGET, verbose=verbose)(FakePage(filt), filt)


# ------------------------------------------------------------------ tests

class WeekSelectionTest(unittest.TestCase):

    def test_switches_from_last_week(self):
        """The ordinary case: one wrong week ticked."""
        f = FakeFilter(WEEKS, ["8/9/2026"])
        _drive(f)
        self.assertEqual(f.checked, {TARGET})

    def test_recovers_from_all_weeks_selected(self):
        """THE 2026-08-16 FAILURE. Every week ticked — the old loop blind-
        toggled the target OFF, then re-selected everything via '(All)', gave
        up after six passes and raised on '(Multiple values)'."""
        f = FakeFilter(WEEKS, WEEKS)
        _drive(f)
        self.assertEqual(f.checked, {TARGET})

    def test_recovers_from_several_weeks_selected(self):
        f = FakeFilter(WEEKS, ["7/26/2026", "8/2/2026", TARGET])
        _drive(f)
        self.assertEqual(f.checked, {TARGET})

    def test_never_touches_another_filter_card(self):
        """Options that are not week-shaped are invisible to the driver — the
        old code unticked them, quietly changing what the view returned."""
        f = FakeFilter(WEEKS, ["8/9/2026"],
                       other_options=("ATT", "Box", "(All Programs)"))
        _drive(f)
        self.assertEqual(f.checked, {TARGET})
        self.assertTrue(all(f.other.values()), "another filter was modified")

    def test_uses_the_only_link_when_present(self):
        f = FakeFilter(WEEKS, WEEKS, has_only_link=True)
        _drive(f)
        self.assertEqual(f.checked, {TARGET})
        self.assertEqual(f.clicks, 1, "the 'Only' link should be one click")

    def test_already_on_target_is_a_noop(self):
        f = FakeFilter(WEEKS, [TARGET])
        _drive(f)
        self.assertEqual(f.checked, {TARGET})
        self.assertEqual(f.clicks, 0)
        self.assertFalse(f.open, "the menu was opened for nothing")

    def test_week_not_posted_yet_leaves_the_selection_alone(self):
        """JE runs a day behind: at a week's start the date isn't in the list.
        Bail quietly — parse()'s staleness guard skips the fill."""
        f = FakeFilter(WEEKS[:-1], ["8/9/2026"])
        _drive(f)
        self.assertEqual(f.checked, {"8/9/2026"})
        self.assertEqual(f.clicks, 0)

    def test_wrong_dropdown_is_left_alone(self):
        """A combobox reading '(All)' that holds no weeks belongs to another
        filter — never click inside it."""
        f = FakeFilter([], [], other_options=("ATT", "Box"))
        f.box_text = lambda: "(All)"
        _drive(f)
        self.assertTrue(all(f.other.values()))

    def test_raises_with_the_stuck_weeks_named(self):
        """A filter that refuses to converge must say WHICH weeks are stuck —
        the menu is gone by the time anyone reads the log."""
        f = FakeFilter(WEEKS, ["7/26/2026", "8/2/2026", TARGET])
        f.toggle = lambda _t: None          # every click is swallowed
        with self.assertRaises(RuntimeError) as cm:
            _drive(f)
        msg = str(cm.exception)
        self.assertIn("(Multiple values)", msg)
        self.assertIn(TARGET, msg)
        self.assertIn("7/26/2026", msg)     # the stuck weeks, by name
        self.assertIn("4 week option(s)", msg)


class OpenDropdownTest(unittest.TestCase):
    """THE 2026-09-20 FAILURE. `tbox.click()` carried no timeout, so a cover
    over the combobox burned Playwright's full 30s default and raised. All
    three crosstab attempts hit the same cover and Retail JE was dropped off
    the board while the rest of it posted."""

    def test_the_open_click_is_bounded(self):
        """No timeout on this click is the whole bug — pin it shut."""
        f = FakeFilter(WEEKS, ["8/9/2026"])
        _drive(f)
        self.assertTrue(f.combo_click_kwargs, "the dropdown was never opened")
        for kw in f.combo_click_kwargs:
            self.assertTrue(kw.get("timeout"),
                            "the combobox click fell back to the 30s default")

    def test_an_intercepted_open_is_retried(self):
        """One intercepted click must not cost the section: clear the cover,
        click again, select the week."""
        f = FakeFilter(WEEKS, ["8/9/2026"], combo_fails=1)
        _drive(f)
        self.assertEqual(f.checked, {TARGET})
        self.assertGreater(f.combo_clicks, 1, "the open was never retried")

    def test_a_dropdown_that_never_opens_leaves_the_week_alone(self):
        """When every pass is intercepted, bail the way an unrecognised
        dropdown already does — quietly, on the view's own week, for parse()'s
        staleness guard to vet. A raised timeout here drops the section."""
        f = FakeFilter(WEEKS, ["8/9/2026"], combo_fails=99,
                       other_options=("ATT", "Box"))
        _drive(f)                       # must not raise
        self.assertEqual(f.checked, {"8/9/2026"}, "the week was changed blind")
        self.assertEqual(f.clicks, 0, "options were clicked in a closed menu")
        self.assertTrue(all(f.other.values()), "another filter was modified")

    def test_the_retry_is_bounded_too(self):
        """Three bounded passes, not an unbounded loop — the budget is what
        keeps a dead viz from eating the rest of the board's pulls."""
        f = FakeFilter(WEEKS, ["8/9/2026"], combo_fails=99)
        _drive(f)
        self.assertLessEqual(f.combo_clicks, 3)


if __name__ == "__main__":
    unittest.main()
