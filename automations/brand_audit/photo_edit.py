"""Auto-enhance + resize photos for social posting.

Two algorithmic (no-AI, fully consistent) passes:
  1. enhance() — lighting cleanup: gray-world white balance, auto-levels,
     gentle shadow lift, mild contrast/saturation, light sharpening. Fixes
     dim / flat / color-cast photos (e.g. warm indoor venue shots). It does
     NOT relight faces, remove harsh shadows, or swap backgrounds — that needs
     a generative tool.
  2. fit_for_ig() — crop to an Instagram-optimal frame (4:5 portrait by
     default; 1:1 square; 1.91:1 landscape; or "auto" = closest to the source).

process_bytes() runs both and returns JPEG bytes ready to post.

Conservative by design — over-processed photos look worse than untouched ones,
so every adjustment is mild and blended.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# Instagram feed targets (width, height), 1080px on the long-fit edge.
IG_SIZES = {
    "4:5": (1080, 1350),    # portrait — most feed real estate, the default
    "1:1": (1080, 1080),    # square
    "1.91:1": (1080, 566),  # landscape
}
DEFAULT_ASPECT = "4:5"


# ---- lighting ---------------------------------------------------------------
def _gray_world_wb(arr: np.ndarray, strength: float = 0.6) -> np.ndarray:
    """Neutralize a color cast by nudging each channel's mean toward gray.
    Clamped + blended so it never over-corrects skin tones."""
    means = arr.reshape(-1, 3).mean(axis=0)
    means[means < 1] = 1
    gray = float(means.mean())
    scale = np.clip(gray / means, 0.8, 1.2)        # cap correction
    scale = 1.0 + (scale - 1.0) * strength          # blend
    return np.clip(arr * scale, 0, 255)


def _shadow_lift(img: Image.Image, gamma: float = 0.92) -> Image.Image:
    """Gentle midtone/shadow lift (gamma < 1) without blowing highlights."""
    inv = 1.0 / gamma
    lut = [min(255, int((i / 255.0) ** inv * 255 + 0.5)) for i in range(256)]
    return img.point(lut * len(img.getbands()))


def enhance(img: Image.Image, intensity: float = 1.0) -> Image.Image:
    """Return a lighting-cleaned copy. intensity scales the whole effect
    (0 = no-op, 1 = default, >1 = stronger)."""
    img = ImageOps.exif_transpose(img).convert("RGB")  # honor camera rotation

    arr = np.asarray(img).astype(np.float32)
    arr = _gray_world_wb(arr, strength=0.6 * intensity)
    img = Image.fromarray(arr.astype("uint8"), "RGB")

    # auto-levels: stretch the histogram, clipping a small tail each end
    img = ImageOps.autocontrast(img, cutoff=0.5)
    img = _shadow_lift(img, gamma=1.0 - 0.08 * intensity)

    img = ImageEnhance.Contrast(img).enhance(1.0 + 0.05 * intensity)
    img = ImageEnhance.Color(img).enhance(1.0 + 0.08 * intensity)
    img = ImageEnhance.Brightness(img).enhance(1.0 + 0.03 * intensity)

    # light sharpening to counter resize softness
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5,
                                             percent=int(60 * intensity),
                                             threshold=2))
    return img


# ---- sizing -----------------------------------------------------------------
def _pick_aspect(w: int, h: int) -> str:
    r = w / h
    if r < 0.9:
        return "4:5"          # portrait
    if r > 1.4:
        return "1.91:1"       # landscape
    return "1:1"              # roughly square


def fit_for_ig(img: Image.Image, aspect: str = DEFAULT_ASPECT) -> Image.Image:
    """Center-crop + scale to an Instagram-optimal frame ('cover' fit, no
    letterbox bars). aspect='auto' picks the standard closest to the source."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    key = _pick_aspect(w, h) if aspect == "auto" else aspect
    tw, th = IG_SIZES[key]

    scale = max(tw / w, th / h)
    nw, nh = round(w * scale), round(h * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


# ---- pipeline ---------------------------------------------------------------
def process_bytes(data: bytes, *, aspect: str = DEFAULT_ASPECT,
                  intensity: float = 1.0, quality: int = 90) -> bytes:
    """Full pipeline: enhance lighting, then crop to an IG frame. Returns JPEG
    bytes. aspect: '4:5' | '1:1' | '1.91:1' | 'auto'."""
    img = Image.open(io.BytesIO(data))
    img = enhance(img, intensity=intensity)
    img = fit_for_ig(img, aspect=aspect)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def main(argv=None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(prog="brand_audit.photo_edit",
                                description="auto-enhance + resize a photo for IG")
    p.add_argument("input", help="source image path")
    p.add_argument("-o", "--output", help="output path (default: <input>_ig.jpg)")
    p.add_argument("--aspect", default=DEFAULT_ASPECT,
                   choices=[*IG_SIZES, "auto"])
    p.add_argument("--intensity", type=float, default=1.0,
                   help="enhancement strength (0=off, 1=default)")
    p.add_argument("--side-by-side", action="store_true",
                   help="also write a before|after comparison")
    args = p.parse_args(argv)

    raw = open(args.input, "rb").read()
    out = process_bytes(raw, aspect=args.aspect, intensity=args.intensity)
    dest = args.output or _suffix(args.input, "_ig")
    open(dest, "wb").write(out)
    print(f"wrote {dest} ({len(out)//1024} KB)")

    if args.side_by_side:
        before = fit_for_ig(Image.open(io.BytesIO(raw)), args.aspect
                            if args.aspect != "auto" else "auto")
        after = Image.open(io.BytesIO(out))
        gap = 16
        canvas = Image.new("RGB", (before.width + after.width + gap,
                                   max(before.height, after.height)), "white")
        canvas.paste(before, (0, 0))
        canvas.paste(after, (before.width + gap, 0))
        cmp = _suffix(args.input, "_compare")
        canvas.save(cmp, format="JPEG", quality=90)
        print(f"wrote {cmp} (before | after)")
    return 0


def _suffix(path: str, suffix: str) -> str:
    import os
    base, _ = os.path.splitext(path)
    return f"{base}{suffix}.jpg"


if __name__ == "__main__":
    import sys
    sys.exit(main())
