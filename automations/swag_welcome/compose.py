"""Write a new hire's name onto the swag-package envelope — in handwriting.

Design decision (Megan 2026-07-13): we do NOT AI-generate a fresh swag image
per person — generated text garbles names and warps the product. Instead we
take the ONE real swag photo (lighting-corrected + cropped by enhance.py) and
composite the name onto the white envelope with Pillow.

"Looks like a real person wrote it, not type" (Megan 2026-07-13): a plain
handwriting FONT still reads as type because every 'e' is identical. So we
render glyph-by-glyph with per-letter jitter — each letter is slightly
resized, rotated, and nudged off the baseline, in pen-blue ink — so no two
letters match and the word wobbles like a real pen stroke. Seeded by the name
so the same name always renders identically.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WORKSPACE = Path(__file__).resolve().parents[2]
RESOURCE_DIR = WORKSPACE / "resources" / "swag"

# --- Asset config ----------------------------------------------------------
CARD_IMAGE_CANDIDATES = [
    RESOURCE_DIR / "swag-card.png",   # enhanced base (enhance.py output)
    RESOURCE_DIR / "swag-card.jpg",
]
# Where the name sits, as FRACTIONS of the image (left, top, right, bottom) —
# fractions survive a re-export at a different resolution. This box is the
# clear white area of the envelope, above the mint tin.
NAME_BOX = (0.11, 0.64, 0.46, 0.80)
# The envelope sits nearly flat in the enhanced crop; tiny tilt to match.
ROTATION_DEG = -1.0
# Pen ink — blue-black, like a real ballpoint on white.
INK = (26, 32, 74)

# Handwriting font (first that exists wins). Bradley Hand reads as casual pen
# print; the per-letter jitter below is what sells "handwritten".
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/System/Library/Fonts/Supplemental/Noteworthy.ttc",
    "/System/Library/Fonts/Supplemental/Chalkboard.ttc",
    "/Library/Fonts/Arial.ttf",
]

# Jitter amounts (fraction of base font size / degrees). Kern stays >= 1.0 and
# a small fixed gap is added so rotated/upscaled letters never overlap — a
# name has to stay perfectly legible.
_SCALE_JITTER = (0.90, 1.08)   # per-letter size wobble
_ROT_JITTER = 5.0              # ± degrees per letter
_BASELINE_JITTER = 0.06        # ± fraction of base size, vertical wobble
_KERN_JITTER = (1.00, 1.06)    # spacing wobble (never < 1.0 → no collisions)
_LETTER_GAP = 0.02             # fixed gap between letters, fraction of base


def _card_image_path() -> Path | None:
    for p in CARD_IMAGE_CANDIDATES:
        if p.exists():
            return p
    return None


def _load_base() -> tuple[Image.Image, bool]:
    real = _card_image_path()
    if real:
        return Image.open(real).convert("RGB"), True
    img = Image.new("RGB", (1200, 900), (245, 241, 232))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 1160, 860], outline=(180, 170, 150), width=4)
    d.text((60, 60), "PLACEHOLDER swag card\n(run enhance.py after adding\n"
           "resources/swag/swag-card-raw.jpg)", fill=(150, 140, 120))
    return img, False


def _font_path() -> str:
    for fp in FONT_CANDIDATES:
        if Path(fp).exists():
            return fp
    return ""


def _render_handwriting(name: str, max_w: int, max_h: int) -> Image.Image:
    """Return a tight RGBA image of `name` in jittered handwriting, sized to
    fit within (max_w, max_h)."""
    fp = _font_path()
    name = name.strip()

    # Try decreasing base sizes until the jittered word fits the box.
    base = max_h
    while base > 24:
        rng = random.Random(f"{name}:{base}")  # deterministic per name+size
        font_full = ImageFont.truetype(fp, base) if fp else ImageFont.load_default()
        asc, desc = font_full.getmetrics()
        pad = int(base * 0.6)
        canvas_h = asc + desc + pad * 2
        canvas = Image.new("RGBA", (max_w * 2, canvas_h), (0, 0, 0, 0))
        cursor = pad
        baseline = pad + asc
        fits = True

        for ch in name:
            sz = max(8, int(base * rng.uniform(*_SCALE_JITTER)))
            font = ImageFont.truetype(fp, sz) if fp else ImageFont.load_default()
            if ch == " ":
                cursor += int(font.getlength(" ") * rng.uniform(*_KERN_JITTER))
                cursor += int(base * _LETTER_GAP)
                continue
            a2, d2 = font.getmetrics()
            adv = int(font.getlength(ch))
            gpad = int(sz * 0.5)
            glyph = Image.new("RGBA", (adv + gpad * 2, a2 + d2 + gpad * 2), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glyph)
            alpha = rng.randint(228, 255)
            gd.text((gpad, gpad), ch, font=font, fill=(*INK, alpha), anchor="la")
            angle = rng.uniform(-_ROT_JITTER, _ROT_JITTER)
            glyph = glyph.rotate(angle, expand=True, resample=Image.BICUBIC)

            # Place so the pre-rotation baseline (gpad + a2) sits on the line,
            # plus a small vertical wobble.
            dy = int(base * rng.uniform(-_BASELINE_JITTER, _BASELINE_JITTER))
            y = baseline - (gpad + a2) + dy - (glyph.height - (a2 + d2 + gpad * 2)) // 2
            canvas.alpha_composite(glyph, (cursor, y))
            cursor += int(adv * rng.uniform(*_KERN_JITTER)) + int(base * _LETTER_GAP)

        bbox = canvas.getbbox()
        if not bbox:
            return canvas
        word = canvas.crop(bbox)
        if word.width <= max_w and word.height <= max_h:
            return word
        base -= max(8, base // 12)

    return canvas.crop(canvas.getbbox()) if canvas.getbbox() else canvas


def compose(name: str, out_path: str | Path) -> dict:
    """Write `name` onto the swag envelope and save to out_path."""
    img, is_real = _load_base()
    img = img.convert("RGBA")
    W, H = img.size
    box = (NAME_BOX[0] * W, NAME_BOX[1] * H, NAME_BOX[2] * W, NAME_BOX[3] * H)
    max_w = int(box[2] - box[0])
    max_h = int(box[3] - box[1])

    word = _render_handwriting(name, max_w, max_h)
    if ROTATION_DEG:
        word = word.rotate(ROTATION_DEG, expand=True, resample=Image.BICUBIC)

    # Center the word within the box.
    cx = int(box[0] + (max_w - word.width) / 2)
    cy = int(box[1] + (max_h - word.height) / 2)
    img.alpha_composite(word, (cx, cy))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path)
    return {"path": str(out_path), "used_real_photo": is_real}
