"""python -m unittest automations.ad_photo_threads.test_crop

A fake Anthropic client only — no real API call, no key needed."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from automations.ad_photo_threads import crop


def _png(w=2000, h=1000) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


class FakeClaude:
    def __init__(self, tiles, stop="end_turn"):
        self.tiles, self.stop, self.calls = tiles, stop, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop, content=[
            SimpleNamespace(type="text", text=json.dumps({"tiles": self.tiles}))])


def _tile(name, found=True, box=(0, 0, 784, 392)):
    x0, y0, x1, y1 = box
    return {"name": name, "found": found, "label_seen": name,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1}


class CropTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(crop, "CACHE_DIR", Path(self.tmp.name))
        p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tile_is_cut_and_scaled_back_to_full_size(self):
        # The model sees 1568x784 (2000x1000 scaled); its box is the left half.
        cl = FakeClaude([_tile("Ana Uno"), _tile("Bo Dos", found=False)])
        out = crop.crop_names(_png(), ["Ana Uno", "Bo Dos"], "F1", client=cl)
        self.assertIsNone(out["Bo Dos"])                   # not seen -> full shot
        w, h = Image.open(io.BytesIO(out["Ana Uno"])).size
        self.assertAlmostEqual(w, 1040, delta=3)           # 1000 + 4% pad
        self.assertAlmostEqual(h, 520, delta=3)
        self.assertIn("1568 x 784", cl.calls[0]["messages"][0]["content"][1]["text"])

    def test_cached_crop_skips_the_model(self):
        crop.crop_names(_png(), ["Ana Uno"], "F1", client=FakeClaude([_tile("Ana Uno")]))
        cl = FakeClaude([])
        out = crop.crop_names(_png(), ["Ana Uno"], "F1", client=cl)
        self.assertTrue(out["Ana Uno"])
        self.assertEqual(cl.calls, [])

    def test_silly_boxes_fall_back_to_full_shot(self):
        tiny = _tile("Ana Uno", box=(10, 10, 30, 30))
        whole = _tile("Bo Dos", box=(0, 0, 1568, 784))
        out = crop.crop_names(_png(), ["Ana Uno", "Bo Dos"], "F2",
                              client=FakeClaude([tiny, whole]))
        self.assertEqual(out, {"Ana Uno": None, "Bo Dos": None})

    def test_model_failure_never_raises(self):
        out = crop.crop_names(_png(), ["Ana Uno"], "F3",
                              client=FakeClaude([], stop="refusal"))
        self.assertEqual(out, {"Ana Uno": None})


if __name__ == "__main__":
    unittest.main()
