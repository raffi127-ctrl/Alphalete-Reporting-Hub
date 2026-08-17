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
        if not self.nodes:
            raise RuntimeError("locator resolved to no node")
        return self.nodes[0]

    def inner_text(self, timeout=None):
        n = self._one()
        # innerText includes descendants', which is what makes the grandparent
        # of a combo read "Filter Contract ID Inclusive (All)".
        return " ".join(x.text for x in n.walk() if x.text).strip()

    def get_attribute(self, name):
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
                 with_all=True, id_names_field=False, titled=True):
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
        self.menu.kids = []
        self.opened = False

    def set_value(self, text):
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

    def test_release_pinned_filters_uses_the_dropdown_path(self):
        """End to end: the expanded-list selector finds nothing (there is no
        _(All) id on the view), so the release must fall through to the dropdown
        instead of reporting 'not on this view' as it did on 8/13."""
        page, viz = build()
        window.release_pinned_filters(page, viz, fields=("Contract ID",),
                                      verbose=False, hydrate_timeout_ms=1)
        self.assertEqual(viz.combo.text, "(All)")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
