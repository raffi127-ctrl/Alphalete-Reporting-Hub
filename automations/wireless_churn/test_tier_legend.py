import tempfile
import unittest
from pathlib import Path

from PIL import Image

from automations.wireless_churn import tier_legend as t


class TierLegendTest(unittest.TestCase):
    def test_raf_examples(self):
        # Raf 2026-11-12: 1-1 = -$70, 1-2 = -$60, 3-3 = baseline, 3-4 = +$10
        self.assertEqual(t.delta_label(1, 1), "-$70")
        self.assertEqual(t.delta_label(1, 2), "-$60")
        self.assertEqual(t.delta_label(3, 3), "BASE")
        self.assertEqual(t.delta_label(3, 4), "+$10")
        self.assertEqual(t.delta_label(4, 2), "$0")

    def test_all_sixteen_combos(self):
        self.assertEqual(len(t.PORT_LINE_PAY), 16)

    def test_legend_on_top_board_below(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.png"
            Image.new("RGB", (324, 100), (1, 2, 3)).save(p)  # a 1-day board
            t.add_to(p)
            im = Image.open(p)
            self.assertGreater(im.height, 100)
            self.assertGreaterEqual(im.width, 324)
            self.assertEqual(im.getpixel((5, im.height - 5)), (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
