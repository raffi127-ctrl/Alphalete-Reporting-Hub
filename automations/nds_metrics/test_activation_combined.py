"""#5 + #6 as one picture (Carlos 2026-11-27: "can 5 & 6 be one
screenshot?"): the Activation Report Overview on top, the Activation
Revenue Overview under it, on white."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from automations.nds_metrics import run as R

D = dt.date(2026, 11, 28)


class Stack(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def pic(self, name, size, color, mode="RGB"):
        p = self.tmp / name
        Image.new(mode, size, color).save(p)
        return p

    def test_one_under_the_other_centred_on_white(self):
        a = self.pic("a.png", (100, 40), (255, 0, 0))
        b = self.pic("b.png", (60, 30), (0, 0, 255))
        out = R.stack_pictures([a, b], self.tmp / "o.png", gap=10)
        im = Image.open(out).convert("RGB")
        self.assertEqual(im.size, (100, 80))
        self.assertEqual(im.getpixel((50, 20)), (255, 0, 0))      # top: overview
        self.assertEqual(im.getpixel((50, 45)), (255, 255, 255))  # the gap
        self.assertEqual(im.getpixel((50, 65)), (0, 0, 255))      # under: revenue
        self.assertEqual(im.getpixel((5, 65)), (255, 255, 255))   # centred, white sides
        self.assertEqual(im.getpixel((95, 65)), (255, 255, 255))

    def test_transparent_goes_white_not_black(self):
        a = self.pic("a.png", (20, 20), (0, 0, 0, 0), mode="RGBA")
        out = R.stack_pictures([a], self.tmp / "o.png")
        self.assertEqual(Image.open(out).convert("RGB").getpixel((10, 10)),
                         (255, 255, 255))


class Combined(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(R, "OUT_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def pic(self, name, h):
        p = self.tmp / name
        Image.new("RGB", (50, h), (10, 10, 10)).save(p)
        return p

    def test_both_halves(self):
        with mock.patch.object(R, "build_activation_overview", lambda *a, **k: self.pic("o.png", 30)), \
                mock.patch.object(R, "build_activation_revenue", lambda *a, **k: self.pic("r.png", 20)):
            out = R.build_activation_combined(None, [], D, log=lambda *a: None)
        self.assertEqual(out.name, "nds_activation_combined.png")
        self.assertEqual(Image.open(out).size, (50, 30 + 24 + 20))

    def test_one_half_failing_posts_the_other(self):
        def boom(*a, **k):
            raise RuntimeError("no SaraPlus")
        with mock.patch.object(R, "build_activation_overview", boom), \
                mock.patch.object(R, "build_activation_revenue", lambda *a, **k: self.pic("r.png", 20)):
            out = R.build_activation_combined(None, [], D, log=lambda *a: None)
        self.assertEqual(Image.open(out).size, (50, 20))

    def test_both_failing_skips_the_section(self):
        def boom(*a, **k):
            raise RuntimeError("no SaraPlus")
        with mock.patch.object(R, "build_activation_overview", boom), \
                mock.patch.object(R, "build_activation_revenue", boom):
            with self.assertRaises(RuntimeError):
                R.build_activation_combined(None, [], D, log=lambda *a: None)


if __name__ == "__main__":
    unittest.main()
