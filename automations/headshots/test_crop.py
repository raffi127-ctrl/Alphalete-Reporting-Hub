"""Where the crop puts the bottom edge — the face has to survive it.

    python -m unittest automations.headshots.test_crop

Synthetic masks only (no rembg, no network): the crop reads the subject's
alpha channel, so a drawn silhouette exercises the real code path.
"""
import unittest

from PIL import Image, ImageDraw

from automations.headshots.process import head_shoulders_box

W, H = 800, 1200


def _subject(bun=None, head=(300, 100, 500, 560), shoulders_y=620,
             shoulders=(40, 760), bottom=H):
    """A silhouette: optional narrow crown, a head, then wide shoulders."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if bun:
        d.rectangle(bun, fill=(0, 0, 0, 255))
    d.rectangle(head, fill=(0, 0, 0, 255))
    d.rectangle((shoulders[0], shoulders_y, shoulders[1], bottom),
                fill=(0, 0, 0, 255))
    return im


class TheFaceSurvives(unittest.TestCase):
    """Jordan Jones, 2026-09-28: her headshot came back as the top of her
    head. The old rule took the widest row in the top 12% as the head width
    — with a top-knot bun that is the BUN — and called the first row 1.55x
    wider the shoulders, which was her forehead."""

    def _bottom(self, im):
        box = head_shoulders_box(im)
        return None if box is None else box[3]

    def test_a_top_knot_bun_does_not_cut_the_face(self):
        face_bottom = 560
        bottom = self._bottom(_subject(bun=(370, 20, 430, 100)))
        self.assertTrue(bottom is None or bottom >= face_bottom,
                        f"crop ended at {bottom}, above the chin at "
                        f"{face_bottom}")

    def test_same_photo_without_the_bun(self):
        bottom = self._bottom(_subject())
        self.assertTrue(bottom is None or bottom >= 560)

    def test_a_full_body_still_crops_to_head_and_shoulders(self):
        # Standing body: head top to shoulder is about a sixth of a person,
        # so head 40-190 over a 40-1200 subject, then the body to the bottom.
        im = _subject(head=(350, 40, 450, 190), shoulders_y=200,
                      shoulders=(280, 520))
        box = head_shoulders_box(im)
        self.assertIsNotNone(box, "a full-body photo should still be cropped")
        self.assertLess(box[3], H * 0.5, "crop should stop near the chest")
        self.assertGreaterEqual(box[3], 140, "crop must keep the whole head")

    def test_a_tight_face_photo_keeps_everything(self):
        # No shoulders in frame at all.
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((200, 50, 600, 1150), fill=(0, 0, 0, 255))
        self.assertIsNone(head_shoulders_box(im))


if __name__ == "__main__":
    unittest.main()
