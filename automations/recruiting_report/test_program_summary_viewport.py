"""The Direct Deposit click points only work at the size they were measured at.

2026-11-23: Lucy 2 (a laptop) gave the DOWNLINEVIEW viz 1408x606 and all three
PROGRAM_SUMMARY_XY_CANDIDATES missed the downline grid, so Carlos's DD column
kept last week's numbers. The scrape now sizes the page up for the click and
puts it back afterwards. No browser here: a fake page records what was asked.

    python -m unittest automations.recruiting_report.test_program_summary_viewport
"""
import unittest
from unittest import mock

from automations.recruiting_report import opt_phase as op


class FakePage:
    def __init__(self, w, h):
        self.size = (w, h)
        self.calls = []

    def evaluate(self, _js):
        return list(self.size)

    def set_viewport_size(self, vp):
        self.calls.append(dict(vp))
        self.size = (vp["width"], vp["height"])


class FitViewportTest(unittest.TestCase):
    def test_small_laptop_window_is_sized_up_and_put_back(self):
        page = FakePage(1408, 644)
        seen = {}

        def inner(pg, *_a, **_k):
            seen["size"] = pg.size
            return ["f"], [["r"]] * 80

        with mock.patch.object(op, "_scrape_one_view_data_inner", inner):
            op._scrape_one_view_data(page, None, "u", False, (0.033, 0.539),
                                     None, op.PROGRAM_SUMMARY_VIEWPORT)
        self.assertEqual(seen["size"], (1664, 949), "clicked at the measured size")
        self.assertEqual(page.size, (1408, 644), "page put back for the next view")

    def test_big_enough_page_is_left_alone(self):
        page = FakePage(1920, 1080)
        with mock.patch.object(op, "_scrape_one_view_data_inner",
                               lambda *a, **k: ([], [])):
            op._scrape_one_view_data(page, None, "u", False, (0.033, 0.539),
                                     None, op.PROGRAM_SUMMARY_VIEWPORT)
        self.assertEqual(page.calls, [])

    def test_no_viewport_asked_changes_nothing(self):
        page = FakePage(800, 600)
        with mock.patch.object(op, "_scrape_one_view_data_inner",
                               lambda *a, **k: ([], [])):
            op._scrape_one_view_data(page, None, "u", False, None, None)
        self.assertEqual(page.calls, [])

    def test_page_is_put_back_even_when_the_scrape_fails(self):
        page = FakePage(1408, 644)

        def boom(*_a, **_k):
            raise RuntimeError("couldn't activate the worksheet")
        with mock.patch.object(op, "_scrape_one_view_data_inner", boom):
            with self.assertRaises(RuntimeError):
                op._scrape_one_view_data(page, None, "u", False, (0.033, 0.539),
                                         None, op.PROGRAM_SUMMARY_VIEWPORT)
        self.assertEqual(page.size, (1408, 644))


if __name__ == "__main__":
    unittest.main()
