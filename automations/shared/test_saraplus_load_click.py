import unittest
from automations.shared import saraplus as S


class LoadRecordsPlaceholder(unittest.TestCase):
    def test_only_the_single_placeholder_row_needs_a_click(self):
        self.assertTrue(S.needs_load_click([["", "Clickto load records."]]))
        self.assertTrue(S.needs_load_click([["", "Click to load records.", ""]]))
        self.assertFalse(S.needs_load_click([]))
        self.assertFalse(S.needs_load_click([["", "History"], ["", "7_History", "10/27/26", "1"]]))
        self.assertFalse(S.needs_load_click([["", "6_Agent", "A REP", "3"]]))

    def test_a_click_that_never_loads_says_so(self):
        class Loc:
            def __init__(self, ok): self.ok = ok
            @property
            def first(self): return self
            def click(self, timeout=0):
                if not self.ok: raise RuntimeError("no such element")
        class Page:
            def locator(self, sel): return Loc(ok="tbody" in sel)
            def wait_for_timeout(self, ms): pass
            def evaluate(self, js, grid): return [["", "Clickto load records."]]
        rows = S._click_load_records(Page(), "#g", [["", "Clickto load records."]])
        self.assertTrue(S.needs_load_click(rows))
        self.assertIn("still the placeholder", S.LAST_LOAD_CLICK["note"])
        self.assertIn("no click via", S.LAST_LOAD_CLICK["note"])

    def test_a_click_that_loads_returns_the_rows(self):
        class Loc:
            @property
            def first(self): return self
            def click(self, timeout=0): pass
        class Page:
            n = 0
            def locator(self, sel): return Loc()
            def wait_for_timeout(self, ms): Page.n += 1
            def evaluate(self, js, grid):
                return [["", "6_Agent", "A REP", "3"]] if Page.n >= 2 else [["", "Clickto load records."]]
        rows = S._click_load_records(Page(), "#g", [["", "Clickto load records."]])
        self.assertEqual(rows[0][1], "6_Agent")
        self.assertIn("rows after click: 1", S.LAST_LOAD_CLICK["note"])


if __name__ == "__main__":
    unittest.main()
