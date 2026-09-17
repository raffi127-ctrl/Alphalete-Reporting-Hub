"""Tests for releasing the BOX view's pinned ID filters.

The failure these lock down cost four days twice (2026-08-13 and again 8/17): a
quick filter that renders as a COLLAPSED dropdown has no items and no field name
anywhere in the DOM until it is opened, so every "is the filter here?" probe
reads zero and the export stays capped to a stale Contract ID list while the
logs say the control was removed.

There's no browser here — a tiny fake stands in for Playwright's locators, built
to the same selectors the real code sends, so a selector change breaks a test
instead of a Monday's numbers.

    python -m unittest automations.box_order_log.test_window_filters -v
"""
from __future__ import annotations

import re
import unittest

from automations.box_order_log import window


# ----------------------------------------------------------------- fake DOM ---

class Node:
    def __init__(self, cls=(), text="", parent=None, **attrs):
        self.cls = list(cls)
        self.text = text
        self.attrs = dict(attrs)
        self.kids = []
        self.parent = parent
        if parent is not None:
            parent.kids.append(self)

    # the handful of attributes the code reads
    def get(self, name):
        if name == "class":
            return " ".join(self.cls)
        return self.attrs.get(name)

    def walk(self):
        yield self
        for k in self.kids:
            yield from k.walk()

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


_TOKEN = re.compile(r'\.([\w-]+)|\[([\w-]+)(?:([*$^]?=)"([^"]*)")?\]')


def _matches(node: Node, compound: str) -> bool:
    """One compound CSS selector — the shapes window.py actually sends."""
    compound = compound.strip()
    if not compound:
        return False
    pos = 0
    for m in _TOKEN.finditer(compound):
        if m.start() != pos:                      # something we don't support
            raise AssertionError(f"unsupported selector {compound!r}")
        pos = m.end()
        cls, attr, op, val = m.groups()
        if cls:
            if cls not in node.cls:
                return False
            continue
        got = node.get(attr)
        if got is None:
            return False
        if op == "=" and got != val:
            return False
        if op == "*=" and val not in got:
            return False
        if op == "$=" and not got.endswith(val):
            return False
        if op == "^=" and not got.startswith(val):
            return False
    return pos == len(compound)


class Loc:
    """Playwright-ish locator over a list of nodes."""

    def __init__(self, nodes, page=None):
        self.nodes = list(nodes)
        self.page = page

    # --- traversal
    def locator(self, sel):
        if sel.startswith("xpath="):
            # The one xpath the code uses: the combo's grandparent, whose text
            # carries "Filter <field> Inclusive" on the live view.
            assert sel == "xpath=../..", sel
            out = []
            for n in self.nodes:
                anc = list(n.ancestors())
                if len(anc) >= 2:
                    out.append(anc[1])
            return Loc(out, self.page)
        out = []
        for n in self.nodes:
            for d in n.walk():
                if d is not n and any(_matches(d, c) for c in sel.split(", ")):
                    out.append(d)
        return Loc(out, self.page)

    @property
    def first(self):
        return Loc(self.nodes[:1], self.page)

    def nth(self, i):
        return Loc(self.nodes[i:i + 1], self.page)

    def count(self):
        return len(self.nodes)

    # --- the node API window.py touches
    def _one(self):
        if not self.nodes or self.nodes[0].attrs.get("_detached"):
            # Playwright would sit on its 30s default here, then raise.
            raise RuntimeError("locator resolved to no node")
        return self.nodes[0]

    def inner_text(self, timeout=None):
        n = self._one()
        # innerText includes descendants', which is what makes the grandparent
        # of a combo read "Filter Contract ID Inclusive (All)".
        return " ".join(x.text for x in n.walk() if x.text).strip()

    def get_attribute(self, name, timeout=None):
        return self._one().get(name)

    def wait_for(self, **_kw):
        if not self.nodes:
            raise RuntimeError("no node")

    def focus(self):
        self.page.focused = self._one()

    def click(self, **_kw):
        self.page.click(self._one())


class Page:
    """Just enough page: a click/keyboard that mutates the fake DOM."""

    def __init__(self, viz):
        self.viz = viz
        self.focused = None
        self.keyboard = self
        self.waits = 0

    # keyboard
    def press(self, key):
        if key == "Escape":
            self.viz.close_menu()
            return
        node = self.focused
        if node is None:
            return
        if key in (" ", "Enter") and "QFCheckbox" in node.cls:
            node.attrs["aria-checked"] = "true"
            self.viz.set_value(node.text)
            return
        if key == "Enter":
            self.click(node)

    def click(self, node):
        if "tabComboBox" in node.cls or node.parent and "tabComboBox" in node.parent.cls:
            self.viz.open_menu()

    def wait_for_timeout(self, _ms):
        self.waits += 1


class Viz:
    """A collapsed quick filter: title + combo, items only once opened."""

    def __init__(self, *, field="Contract ID", value="Multiple values",
                 with_all=True, id_names_field=False, titled=True,
                 slow_value=False):
        # slow_value: the combo keeps its old text while Tableau re-queries, so
        # the only proof of the tick is the item itself (2026-09-15).
        self.slow_value = slow_value
        self.root = Node(cls=["viz"])
        card = Node(cls=["tab-filterCard"], parent=self.root)
        # The live view (probed 2026-08-17): the label sentence lives in its own
        # node, pointed at by aria-labelledby; the combo itself says only the
        # VALUE. `titled=False` models a build that drops the attribute, where
        # the grandparent text is the only place the field name survives.
        lab_id = "tab-ui-id-{}".format(abs(hash(field)) % 10 ** 6)
        Node(cls=["label"], text="Filter {} Inclusive".format(field),
             parent=card, id=lab_id)
        combo_attrs = {"id": f"combo:{field}"} if id_names_field else {"id": "combo:x"}
        if titled:
            combo_attrs["aria-labelledby"] = lab_id
        holder = Node(cls=["comboHolder"], parent=card)
        self.combo = Node(cls=["tabComboBox"], text=value, parent=holder,
                          **combo_attrs)
        Node(cls=["tabComboBoxButton"], parent=self.combo)
        self.menu = Node(cls=["tabMenu"], parent=self.root)
        self.with_all = with_all
        self.opened = False

    # the fake browser's side effects
    def open_menu(self):
        if self.opened:
            return
        self.opened = True
        if self.with_all:
            Node(cls=["QFCheckbox"], text="(All)", parent=self.menu,
                 **{"role": "checkbox", "aria-checked": "false"})
        for i in range(3):
            Node(cls=["QFCheckbox"], text=f"C-{i}", parent=self.menu,
                 **{"role": "checkbox", "aria-checked": "true"})

    def close_menu(self):
        for k in self.menu.kids:
            k.attrs["_detached"] = True      # the live DOM drops them on close
        self.menu.kids = []
        self.opened = False

    def set_value(self, text):
        if not self.slow_value:
            self.combo.text = text

    # the frame_locator API
    def locator(self, sel):
        return Loc([self.root], Page.current).locator(sel)


def build(**kw):
    viz = Viz(**kw)
    page = Page(viz)
    Page.current = page
    return page, viz


# --------------------------------------------------------------------- tests ---

class DropdownReleaseTest(unittest.TestCase):
    def test_collapsed_dropdown_is_found_by_title_and_ticked(self):
        """The 8/17 shape: nothing carries the field name, the value reads
        'Multiple values', and the (All) item only exists once it's open."""
        page, viz = build()
        self.assertEqual(window._release_dropdown(page, viz, "Contract ID", True),
                         "released")
        self.assertEqual(viz.combo.text, "(All)")

    def test_found_by_id_when_the_build_names_the_field(self):
        page, viz = build(id_names_field=True)
        combo, how = window._field_combo(viz, "Contract ID")
        self.assertEqual(how, "attribute")
        self.assertEqual(window._release_dropdown(page, viz, "Contract ID", True),
                         "released")

    def test_already_all_is_left_alone(self):
        page, viz = build(value="(All)")
        self.assertEqual(window._release_dropdown(page, viz, "Contract ID", True),
                         "released")
        self.assertFalse(viz.opened, "no need to open a filter already at (All)")

    def test_no_combo_for_the_field_is_absent_not_stuck(self):
        """'absent' must stay distinguishable from 'stuck': the caller only
        retries — and only warns — when the control is really there."""
        page, viz = build(field="Some Other Field")
        self.assertEqual(window._release_dropdown(page, viz, "Contract ID", True),
                         "absent")

    def test_dropdown_without_an_all_item_is_stuck(self):
        page, viz = build(with_all=False)
        self.assertEqual(window._release_dropdown(page, viz, "Contract ID", True),
                         "stuck")

    def test_tick_is_read_before_the_menu_closes(self):
        """2026-09-15: the combo still read 'Multiple values' while the view
        re-queried, and the code asked the (All) item for aria-checked AFTER
        Escape had detached it — a 30s timeout and an 'error' verdict for a
        release that had worked."""
        page, viz = build(slow_value=True)
        self.assertEqual(window._release_dropdown(page, viz, "Contract ID", True),
                         "released")

    def test_release_pinned_filters_uses_the_dropdown_path(self):
        """End to end: the expanded-list selector finds nothing (there is no
        _(All) id on the view), so the release must fall through to the dropdown
        instead of reporting 'not on this view' as it did on 8/13."""
        page, viz = build()
        window.release_pinned_filters(page, viz, fields=("Contract ID",),
                                      verbose=False, hydrate_timeout_ms=1)
        self.assertEqual(viz.combo.text, "(All)")



class HookOrderTest(unittest.TestCase):
    """2026-09-16: the saved window (12/9-20/9) held no sales, so the ID
    dropdowns listed nothing — no (All) to tick — and every pull aborted before
    the dates were ever widened. The dates must move first."""

    def test_dates_are_widened_before_the_id_filters_are_released(self):
        import datetime as dt
        from unittest import mock

        steps = []

        class Box:
            def __init__(self, label):
                self.label = label
                self.first = self

            def wait_for(self, **_):
                pass

            def click(self, **_):
                pass

            def fill(self, value):
                steps.append(("date", self.label))

            def press(self, _key):
                pass

        class HookViz:
            def locator(self, sel):
                return Box(re.search(r'aria-label="([^"]+)"', sel).group(1))

        class HookPage:
            def wait_for_timeout(self, _ms):
                pass

        def release(*_a, **_k):
            steps.append(("release",))
            return {}

        with mock.patch.object(window, "release_pinned_filters", release),                 mock.patch.object(window, "confirm_release", lambda *a, **k: True):
            window.date_window_hook(dt.date(2026, 7, 7), dt.date(2026, 9, 16),
                                    verbose=False)(HookPage(), HookViz())

        self.assertEqual(steps, [("date", "Start Date"), ("date", "End Date"),
                                 ("release",)])


class LabelFoldTest(unittest.TestCase):
    """2026-09-16/17: an SCI re-publish put an invisible character in the filter
    label, and a present filter must not read as 'absent' because of it."""

    def test_invisible_characters_do_not_hide_a_filter(self):
        from automations.box_order_log import window as w
        for label in ("Filter ﻿Contract ID Inclusive (All)",
                      "Filter Contract ID Inclusive",
                      "Filter Contract​ ID",
                      "Filter ACCOUNT ID"):
            field = "Account Id" if "ACCOUNT" in label else "Contract ID"
            self.assertIn(w._fold(field), w._fold(label), label)

    def test_a_different_field_still_does_not_match(self):
        from automations.box_order_log import window as w
        self.assertNotIn(w._fold("Contract ID"),
                         w._fold("Filter Owner & Office Inclusive"))


class TextBoxFilterTest(unittest.TestCase):
    """2026-09-17: Contract ID / Account Id became free-text boxes. Empty is
    clean; a typed value is a pin and gets cleared; neither is 'absent'."""

    class Box:
        def __init__(self, label, value=""):
            self.label, self.value = label, value

        def get_attribute(self, name):
            return self.label if name == "aria-label" else None

        def input_value(self, **_):
            return self.value

        def fill(self, value):
            self.value = value

        def press(self, _key):
            pass

    class Boxes:
        def __init__(self, boxes):
            self.boxes = boxes

        def count(self):
            return len(self.boxes)

        def nth(self, i):
            return self.boxes[i]

    class Viz:
        def __init__(self, boxes):
            self.boxes = boxes

        def locator(self, sel):
            return TextBoxFilterTest.Boxes(
                self.boxes if sel.startswith("textarea") else [])

    class Page:
        def wait_for_timeout(self, _ms):
            pass

    def _release(self, value):
        box = self.Box("Contract﻿ ID", value)
        viz = self.Viz([self.Box("Start Date", "1/8/2026"), box])
        found = window._text_filter(viz, "Contract ID")
        self.assertIs(found, box)
        return window._release_text(self.Page(), "Contract ID", found, False), box

    def test_empty_box_is_confirmed_clean(self):
        verdict, _ = self._release("")
        self.assertIn(verdict, window.CONFIRMED_CLEAN)

    def test_typed_value_is_cleared(self):
        verdict, box = self._release("289147")
        self.assertEqual(verdict, "released")
        self.assertEqual(box.value, "")

    def test_other_boxes_do_not_match(self):
        viz = self.Viz([self.Box("Start Date"), self.Box("Business Name")])
        self.assertIsNone(window._text_filter(viz, "Contract ID"))


class UnlabelledTextBoxTest(unittest.TestCase):
    """09:16 probe: the ID boxes carry no aria-label; the title above names them."""

    class Up:
        def __init__(self, text):
            self.text = text

        def inner_text(self, **_):
            return self.text

    class Box(TextBoxFilterTest.Box):
        def __init__(self, title, value="", aria=None):
            super().__init__(aria, value)
            self.title = title

        def locator(self, sel):
            return UnlabelledTextBoxTest.Up(
                self.title if sel == "xpath=../.." else "")

    class Viz(TextBoxFilterTest.Viz):
        def locator(self, sel):
            return TextBoxFilterTest.Boxes(
                [] if sel.startswith("textarea") else self.boxes)

    def test_found_by_the_title_above_it(self):
        box = self.Box("Contract ID")
        viz = self.Viz([self.Box("Business Name"), box])
        self.assertIs(window._text_filter(viz, "Contract ID"), box)

    def test_a_long_container_text_is_not_a_title(self):
        viz = self.Viz([self.Box("Start Date End Date Owner & Office Rep Name "
                                 "Contract ID Account Id")])
        self.assertIsNone(window._text_filter(viz, "Contract ID"))


class QueryBoxLabelTest(unittest.TestCase):
    """09:25 probe: textarea.QueryBox labelled 'Filter Account Id Inclusive'."""

    def test_wrapped_label_matches(self):
        T = TextBoxFilterTest
        box = T.Box("Filter Account Id Inclusive")
        viz = T.Viz([T.Box("Start Date", "8/1/2026"),
                     T.Box("Filter Business Name Inclusive"), box])
        self.assertIs(window._text_filter(viz, "Account Id"), box)
        self.assertIsNone(window._text_filter(viz, "Contract ID"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
