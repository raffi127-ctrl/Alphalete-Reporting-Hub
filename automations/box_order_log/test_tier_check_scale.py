"""The empty/clipped checks scale with the export's width (Lucy 1, 2026-10-14:
a full 8-rep board exported at 1000x384 was rejected as empty)."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from automations.box_order_log import tier_bonus as T


def _png(d, w, h):
    p = Path(d) / "{}x{}.png".format(w, h)
    Image.new("RGB", (w, h), "white").save(p)
    return p


class TierCheckScaleTest(unittest.TestCase):
    def test_half_scale_full_board_passes(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(T._check(_png(d, 1000, 384), "Ryan McSpadden"), "")

    def test_full_scale_full_board_passes(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(T._check(_png(d, 2000, 753), "Ryan McSpadden"), "")

    def test_empty_board_still_raises_at_either_scale(self):
        with tempfile.TemporaryDirectory() as d:
            for w, h in ((2000, 330), (1000, 165)):
                with self.assertRaises(RuntimeError):
                    T._check(_png(d, w, h), "Ryan McSpadden")

    def test_clip_warning_scales_too(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(T._check(_png(d, 1000, 720), "Carlos Hidalgo"))


if __name__ == "__main__":
    unittest.main()
