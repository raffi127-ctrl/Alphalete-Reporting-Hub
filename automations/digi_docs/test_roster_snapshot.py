"""A roster read has to be able to prove it read everything.

2026-09-14. The RES-AT&T campaign logged

    RES-AT&T: read 1440, table says 117  (+24 new)

and passed its own completeness check on it. 1440 is 24 rows read sixty times:
the Next button is there, is enabled, clicks without error, and does not
advance the table. So the roster held the first 24 of 117 people, 93 were never
looked at, and the guard that exists to catch exactly that waved it through —
because it compared rows READ, duplicates and all, against the table's count.

That matters more here than a wrong number usually does: `add_sales_rep` trusts
a proven roster to decide who is absent, and adding someone MAILS them their
onboarding email. An under-read roster calls real people absent and welcomes
them twice.

These tests pin both halves: the count is distinct rows, and the length menu
(not the Next walk) is what gets the whole table into the DOM.
"""
from __future__ import annotations

import unittest

from automations.digi_docs import ownerville as ov


class _Cell:
    def __init__(self, text):
        self._t = text

    def inner_text(self, timeout=0):
        return self._t


class _Rows:
    def __init__(self, table):
        self._t = table

    def count(self):
        return len(self._t.visible())

    def nth(self, i):
        return _Cell(self._t.visible()[i])


class _LengthMenu:
    def __init__(self, table):
        self._t = table

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def evaluate(self, script):
        return list(self._t.length_menu)

    def select_option(self, index=None, **kw):
        value = int(self._t.length_menu[index])
        self._t.page_size = self._t.total if value < 0 else value
        self._t.page = 0


class _Absent:
    """An element that is not on the page at all."""

    @property
    def first(self):
        return self

    def count(self):
        return 0

    def evaluate(self, script):
        raise AssertionError("evaluated an element that is not there")


class _Next:
    """There, enabled, clicks cleanly — and does not move. The real one."""

    def __init__(self, table):
        self._t = table

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def get_attribute(self, name):
        return "disabled" if self._t.on_last_page() else ""

    def evaluate(self, script):
        return ""

    def click(self):
        if self._t.next_works:
            self._t.page += 1


class _Info:
    def __init__(self, table):
        self._t = table

    @property
    def first(self):
        return self

    def inner_text(self, timeout=0):
        return (f"Showing 1 to {len(self._t.visible())} of "
                f"{self._t.total} entries")


class FakeTable:
    """Just enough DataTables for the reader under test."""

    def __init__(self, total=117, page_size=24, length_menu=("10", "24", "-1"),
                 next_works=False):
        self.total = total
        self.page_size = page_size
        self.page = 0
        self.length_menu = list(length_menu)
        self.next_works = next_works
        self.names = ["%d rep %d" % (i, i) for i in range(total)]

    def visible(self):
        start = self.page * self.page_size
        return self.names[start:start + self.page_size]

    def on_last_page(self):
        return (self.page + 1) * self.page_size >= self.total

    # --- the slice of a patchright page the reader touches ---
    def locator(self, selector):
        if "tbody tr" in selector:
            return _Rows(self)
        if "_length" in selector:
            return _LengthMenu(self) if self.length_menu else _Absent()
        if "_info" in selector or "dataTables_info" in selector:
            return _Info(self)
        if "Next" in selector or "next" in selector:
            return _Next(self)
        raise AssertionError("unexpected selector: %s" % selector)

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass


class ReadPagesCounts(unittest.TestCase):

    def test_the_all_option_puts_the_whole_roster_in_the_dom(self):
        """With the length menu on All, one page IS the roster — no Next
        needed, which is the point, because Next is the part that is broken."""
        t = FakeTable(next_works=False)
        seen = set()
        self.assertEqual(117, ov._read_pages(t, seen))
        self.assertEqual(117, len(seen))
        self.assertEqual(117, ov._entries_total(t))

    def test_a_next_that_never_advances_reports_what_it_actually_saw(self):
        """No length menu, dead Next: the honest answer is 24, and 24 is short
        of the 117 the table claims, so `snapshot` must call this INCOMPLETE.
        The old count said 1440 here and the check passed."""
        t = FakeTable(length_menu=(), next_works=False)
        seen = set()
        read = ov._read_pages(t, seen)
        self.assertEqual(24, read)
        self.assertEqual(24, len(seen))
        self.assertLess(read, ov._entries_total(t),
                        "an under-read roster has to fail the entries check")

    def test_a_working_next_still_walks_every_page(self):
        """The fallback is kept, not replaced."""
        t = FakeTable(length_menu=(), next_works=True)
        seen = set()
        self.assertEqual(117, ov._read_pages(t, seen))

    def test_rows_seen_accumulates_across_campaigns(self):
        """snapshot() passes ONE set across every campaign and prints the
        '+N new' from its growth."""
        seen = {"someone from an earlier campaign"}
        ov._read_pages(FakeTable(total=5, page_size=5, length_menu=()), seen)
        self.assertEqual(6, len(seen))


class ShowAllEntries(unittest.TestCase):

    def test_all_beats_the_numbered_options(self):
        """DataTables spells All as -1. Read as a number it loses to 10, which
        is how 'widen the page size' quietly narrows it."""
        t = FakeTable(length_menu=("10", "24", "50", "-1"))
        self.assertGreater(ov._show_all_entries(t), 50)
        self.assertEqual(117, t.page_size)

    def test_no_menu_is_not_a_crash(self):
        t = FakeTable(length_menu=())
        self.assertEqual(0, ov._show_all_entries(t))


if __name__ == "__main__":
    unittest.main()
