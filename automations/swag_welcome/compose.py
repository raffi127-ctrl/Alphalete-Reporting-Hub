"""Write a new hire's name onto the swag-package envelope — in Megan's OWN
handwriting.

Design (Megan 2026-07-13): a handwriting FONT reads as type even with jitter,
so we DON'T use one. build_glyphs.py cut Megan's real letters out of a
handwriting sample into a glyph library (resources/swag/glyphs/). Here we STAMP
those actual ink strokes to spell each name — real strokes, real ink texture,
baseline-aligned from measured metrics. Repeated letters get a slight per-
occurrence rotate/scale so they don't look copy-pasted. The word is then
multiply-blended onto the envelope so it sinks into the paper.

If the glyph library is missing, falls back to a plain handwriting font so the
pipeline still runs.
"""

from __future__ import annotations

import json
import random
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

WORKSPACE = Path(__file__).resolve().parents[2]
RESOURCE_DIR = WORKSPACE / "resources" / "swag"
GLYPH_DIR = RESOURCE_DIR / "glyphs"

CARD_IMAGE_CANDIDATES = [
    RESOURCE_DIR / "swag-card.png",
    RESOURCE_DIR / "swag-card.jpg",
]
# Where the name sits, as FRACTIONS of the image (left, top, right, bottom).
NAME_BOX = (0.11, 0.64, 0.46, 0.80)
ROTATION_DEG = -1.0
GLYPH_INK = (24, 28, 46)
OUT_MAX_PX = 1200   # longest side of the saved card — small + fast to paste

# Layout tuning (fractions of the average glyph width / line height).
_GAP = 0.02           # space between letters — tight, like real writing
_SPACE = 0.42         # width of a blank space
_ROT_JITTER = 3.0     # ± deg per stamped letter
_SCALE_JITTER = 0.05  # ± fraction per letter
_BASE_JITTER = 0.04   # ± vertical wobble, fraction of cap height
# Capital-letter height as a fraction of the name box height. Fixed (not fit-
# to-box) so EVERY name is written at the same size, like a real person —
# longer names just use more width (and only shrink if they'd overflow).
_CAP_FRAC = 0.34


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
    d.text((60, 60), "PLACEHOLDER — run enhance.py", fill=(150, 140, 120))
    return img, False


@lru_cache(maxsize=1)
def _metrics() -> dict:
    p = GLYPH_DIR / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}


@lru_cache(maxsize=128)
def _glyph(tag: str, letter: str) -> Image.Image | None:
    sub = "upper" if tag == "U" else "lower"
    p = GLYPH_DIR / sub / f"{letter}.png"
    return Image.open(p).convert("RGBA") if p.exists() else None


def _char_glyph(ch: str):
    """Return (image, metric) for a character, or None. Strips accents so 'í'→'i'."""
    if ch.isupper():
        tag, key = "U", ch
    else:
        tag, key = "l", ch
    img = _glyph(tag, key)
    if img is None:
        return None
    m = _metrics().get(f"{tag}:{key}", {"asc": img.height, "desc": 0})
    return img, m


def _strip_accents(name: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", name)
                   if not unicodedata.combining(c))


def _titlecase(name: str) -> str:
    """Capitalize the first letter of each word — names always start with a
    capital ('james' → 'James'), and the capital glyphs are the clean ones."""
    return " ".join(w[:1].upper() + w[1:] if w else w for w in name.split(" "))


def _render_from_glyphs(name: str) -> Image.Image | None:
    """Stamp Megan's real letters into a word (RGBA), baseline-aligned, jittered.
    Returns None if the glyph library isn't available."""
    if not _metrics():
        return None
    name = _titlecase(_strip_accents(name))
    rng = random.Random(name)

    avg_w = sum(m["w"] for m in _metrics().values()) / len(_metrics())
    cap = max(m["asc"] for m in _metrics().values())
    gap = int(avg_w * _GAP)

    placed = []          # (image, x, top_relative_to_baseline)
    cursor = 0
    for ch in name:
        if ch in " -_":
            cursor += int(avg_w * _SPACE)
            continue
        got = _char_glyph(ch) or _char_glyph(ch.lower()) or _char_glyph(ch.upper())
        if not got:
            cursor += int(avg_w * _SPACE)
            continue
        img, m = got
        # per-occurrence variation so repeats (e.g. "nn") differ
        s = 1.0 + rng.uniform(-_SCALE_JITTER, _SCALE_JITTER)
        if s != 1.0:
            img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))),
                             Image.LANCZOS)
        ang = rng.uniform(-_ROT_JITTER, _ROT_JITTER)
        pre_h = img.height
        img = img.rotate(ang, expand=True, resample=Image.BICUBIC)
        asc = m["asc"] * s
        # top of glyph relative to baseline (y up = negative), + wobble
        top = -asc + (img.height - pre_h) / 2 + rng.uniform(-_BASE_JITTER, _BASE_JITTER) * cap
        placed.append((img, cursor, top))
        cursor += img.width + gap

    if not placed:
        return None

    top_min = min(t for _, _, t in placed)
    bot_max = max(t + im.height for im, _, t in placed)
    total_w = max(x + im.width for im, x, _ in placed)
    H = int(bot_max - top_min) + 4
    W = int(total_w) + 4
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for im, x, top in placed:
        canvas.alpha_composite(im, (int(x), int(top - top_min)))
    return canvas.crop(canvas.getbbox())


# ---- font fallback (only if the glyph library is missing) ----------------
_FALLBACK_FONTS = ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
                   "/Library/Fonts/Arial.ttf"]


def _render_fallback(name: str, max_w: int, max_h: int) -> Image.Image:
    fp = next((f for f in _FALLBACK_FONTS if Path(f).exists()), None)
    size = max_h
    while size > 20:
        font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        tmp = Image.new("RGBA", (max_w * 2, max_h * 3), (0, 0, 0, 0))
        d = ImageDraw.Draw(tmp)
        d.text((10, 10), name, font=font, fill=(*GLYPH_INK, 255))
        bbox = tmp.getbbox()
        if bbox and (bbox[2] - bbox[0]) <= max_w and (bbox[3] - bbox[1]) <= max_h:
            return tmp.crop(bbox)
        size -= 8
    return tmp.crop(tmp.getbbox()) if tmp.getbbox() else tmp


def compose(name: str, out_path: str | Path) -> dict:
    """Write `name` onto the swag envelope and save to out_path."""
    img, is_real = _load_base()
    img = img.convert("RGB")
    W, H = img.size
    box = (NAME_BOX[0] * W, NAME_BOX[1] * H, NAME_BOX[2] * W, NAME_BOX[3] * H)
    max_w = int(box[2] - box[0])
    max_h = int(box[3] - box[1])

    word = _render_from_glyphs(name)
    used_handwriting = word is not None
    if word is None:
        word = _render_fallback(name, max_w, max_h)

    # Fixed writing size: scale so capitals are a consistent height across all
    # names; then shrink (only if needed) so a long name still fits the box.
    if used_handwriting:
        src_cap = max(m["asc"] for m in _metrics().values())
        # word.height ≈ src_cap * (its own scale); use the global cap as the
        # reference so every name renders at the same pen size.
        target_cap = _CAP_FRAC * max_h
        scale = target_cap / src_cap
    else:
        scale = min(max_w / word.width, max_h / word.height, 1.0)
    scale = min(scale, max_w / word.width, max_h / word.height)
    word = word.resize((max(1, int(word.width * scale)),
                        max(1, int(word.height * scale))), Image.LANCZOS)
    if ROTATION_DEG:
        word = word.rotate(ROTATION_DEG, expand=True, resample=Image.BICUBIC)

    cx = int(box[0] + (max_w - word.width) / 2)
    cy = int(box[1] + (max_h - word.height) / 2)

    # Multiply-blend the ink into the paper (paper texture shows through).
    alpha = word.split()[3]
    region = img.crop((cx, cy, cx + word.width, cy + word.height))
    ink_layer = Image.new("RGB", region.size, GLYPH_INK)
    inked = ImageChops.multiply(region, ink_layer)
    blended = Image.composite(inked, region, alpha)
    img.paste(blended, (cx, cy))

    # Downscale + JPEG so the card is a normal-sized photo (~a few hundred KB),
    # not a 15 MB PNG — big files send as an undelivered "file" in iMessage
    # instead of an inline image.
    if max(img.size) > OUT_MAX_PX:
        s = OUT_MAX_PX / max(img.size)
        img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        img.convert("RGB").save(out_path, "JPEG", quality=88, optimize=True)
    else:
        img.save(out_path)
    return {"path": str(out_path), "used_real_photo": is_real,
            "used_handwriting": used_handwriting}
