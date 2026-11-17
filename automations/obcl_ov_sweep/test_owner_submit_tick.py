"""The confirm box gets ticked even when the real input is hidden behind its
label, and is never clicked twice once it reads checked (2026-11-17)."""
import unittest

from automations.obcl_ov_sweep.owner_submit import _tick


class _Page:
    def wait_for_timeout(self, ms):
        pass


class _Box:
    def __init__(self, hidden=True):
        self.on, self.hidden, self.clicks, self.page = False, hidden, 0, _Page()

    def is_checked(self):
        return self.on

    def click(self, timeout=0, force=False):
        if self.hidden and not force:
            raise TimeoutError("element is not visible")
        if self.hidden:
            raise RuntimeError("no bounding box")
        self.clicks += 1
        self.on = not self.on

    def evaluate(self, js):
        self.clicks += 1
        self.on = not self.on


class _Label:
    def __init__(self, box, works=True):
        self.box, self.works, self.clicks = box, works, 0

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def click(self, timeout=0):
        self.clicks += 1
        if self.works:
            self.box.on = not self.box.on


class TickTest(unittest.TestCase):
    def test_hidden_input_ticks_through_label(self):
        box = _Box(hidden=True)
        lab = _Label(box)
        self.assertTrue(_tick(lab, box))
        self.assertTrue(box.on)
        self.assertEqual((lab.clicks, box.clicks), (1, 0))

    def test_label_dead_falls_back_to_dom_click(self):
        box = _Box(hidden=True)
        lab = _Label(box, works=False)
        self.assertTrue(_tick(lab, box))
        self.assertEqual(box.clicks, 1)             # one DOM click, no toggle-back

    def test_visible_input_never_clicked_after_label_ticks(self):
        box = _Box(hidden=False)
        lab = _Label(box)
        self.assertTrue(_tick(lab, box))
        self.assertEqual(box.clicks, 0)
        self.assertTrue(box.on)

    def test_nothing_works_says_so(self):
        box = _Box(hidden=True)
        box.evaluate = lambda js: None
        self.assertFalse(_tick(_Label(box, works=False), box))


if __name__ == "__main__":
    unittest.main()
