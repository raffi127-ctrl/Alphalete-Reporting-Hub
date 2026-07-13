"""Turn the raw swag phone-photo into a cleaner, brighter base image.

Run once when the photo changes; output is the committed base that compose.py
writes names onto:
    python -m automations.swag_welcome.enhance

Keeps the raw original untouched (swag-card-raw.jpg) so we can re-tune.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, ImageEnhance

RESOURCE_DIR = Path(__file__).resolve().parents[2] / "resources" / "swag"
RAW = RESOURCE_DIR / "swag-card-raw.jpg"
OUT = RESOURCE_DIR / "swag-card.png"

# Crop as fractions of the raw image (left, top, right, bottom). Trims dead
# wall/table without losing any swag item.
CROP = (0.045, 0.055, 0.985, 0.965)


def enhance() -> Path:
    im = ImageOps.exif_transpose(Image.open(RAW)).convert("RGB")
    W, H = im.size
    im = im.crop((int(CROP[0] * W), int(CROP[1] * H),
                  int(CROP[2] * W), int(CROP[3] * H)))

    # Lift the dim, warm phone exposure: brighten, add contrast + pop, and
    # cool the yellow cast slightly by nudging the channel balance.
    im = ImageEnhance.Brightness(im).enhance(1.10)
    im = ImageEnhance.Contrast(im).enhance(1.12)
    im = ImageEnhance.Color(im).enhance(1.12)
    r, g, b = im.split()
    r = r.point(lambda v: max(0, int(v * 0.97)))
    b = b.point(lambda v: min(255, int(v * 1.04)))
    im = Image.merge("RGB", (r, g, b))
    im = ImageEnhance.Sharpness(im).enhance(1.25)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT)
    return OUT


if __name__ == "__main__":
    p = enhance()
    print("wrote", p, Image.open(p).size)
