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

# iPhone photos are HEIC by default — register the opener so Pillow can read them
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

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
    """Return a lighting-cleaned copy. Tuned to NEVER blow out highlights or
    amplify grain: white-balance is clamped, auto-levels only lifts the black
    point (never clips the bright end), brightening is adaptive (only when the
    photo is dark) via a highlight-preserving gamma curve, and sharpening is
    mild with a high threshold so flat/noisy areas are left alone.
    intensity scales the effect (0 = no-op, 1 = default)."""
    img = ImageOps.exif_transpose(img).convert("RGB")  # honor camera rotation

    arr = np.asarray(img).astype(np.float32)
    arr = _gray_world_wb(arr, strength=0.5 * intensity)
    img = Image.fromarray(arr.astype("uint8"), "RGB")

    # auto-levels: lift the black point a hair, but cutoff=(low, 0) means the
    # highlight end is NEVER clipped -> no new blown-out areas.
    img = ImageOps.autocontrast(img, cutoff=(0.5, 0.0))

    # brighten ONLY if the photo is genuinely dark, and via gamma (which rolls
    # off toward white instead of hard-clipping it).
    mean_lum = float(np.asarray(img.convert("L"), dtype=np.float32).mean())
    if mean_lum < 110:
        lift = min(0.16, (110 - mean_lum) / 110 * 0.20) * intensity
        img = _shadow_lift(img, gamma=1.0 - lift)

    img = ImageEnhance.Contrast(img).enhance(1.0 + 0.04 * intensity)
    img = ImageEnhance.Color(img).enhance(1.0 + 0.07 * intensity)

    # gentle, noise-aware sharpen (threshold=3 skips flat/noisy regions)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2,
                                             percent=int(45 * intensity),
                                             threshold=3))
    return img


# ---- sizing -----------------------------------------------------------------
def _pick_aspect(w: int, h: int) -> str:
    r = w / h
    if r < 0.9:
        return "4:5"          # portrait
    if r > 1.4:
        return "1.91:1"       # landscape
    return "1:1"              # roughly square


def fit_for_ig(img: Image.Image, aspect: str = DEFAULT_ASPECT,
               zoom: float = 1.0) -> Image.Image:
    """Center-crop to an Instagram-optimal aspect ('cover' fit, no letterbox
    bars). NEVER upscales — if the source can't fill 1080px we keep the native
    crop (slightly smaller but crisp) rather than enlarging it into grain.
    aspect='auto' picks the standard closest to the source. zoom>1 crops tighter
    (e.g. 1.3 = ~30% more zoomed in on the center)."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    key = _pick_aspect(w, h) if aspect == "auto" else aspect
    tw, th = IG_SIZES[key]
    ar = tw / th

    # largest center crop of the target aspect that fits at native resolution
    if w / h > ar:
        cw, ch = int(round(h * ar)), h
    else:
        cw, ch = w, int(round(w / ar))
    # tighter crop = take a smaller centered region (keeps aspect), then scale up
    if zoom and zoom > 1.0:
        cw, ch = max(1, int(cw / zoom)), max(1, int(ch / zoom))
    left, top = (w - cw) // 2, (h - ch) // 2
    img = img.crop((left, top, left + cw, top + ch))

    # only ever downscale to the target; never enlarge
    if cw > tw:
        img = img.resize((tw, th), Image.LANCZOS)
    return img


# ---- pipeline ---------------------------------------------------------------
def blur_variance(img_bytes: bytes) -> float:
    """Sharpness score = variance of the Laplacian (higher = sharper). Computed
    on a size-normalized grayscale copy so it's comparable across photos."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(img_bytes))).convert("L")
    w, h = im.size
    s = 1000.0 / max(w, h)
    im = im.resize((max(2, int(w * s)), max(2, int(h * s))))
    g = np.asarray(im, dtype=np.float64)
    lap = (4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1]
           - g[1:-1, :-2] - g[1:-1, 2:])
    return float(lap.var())


# below this sharpness score a photo is too blurry to meet posting standards
BLUR_THRESHOLD = 80.0


def is_too_blurry(img_bytes: bytes, threshold: float = BLUR_THRESHOLD) -> bool:
    """True if the photo is too blurry to post even after our enhancement."""
    return blur_variance(img_bytes) < threshold


def quality_report(data: bytes, aspect: str = DEFAULT_ASPECT) -> dict:
    """Inspect the SOURCE photo for problems we can't fix (too low-res to be
    crisp, already blown-out, very dark/crushed). Returns a dict with `ok` and
    human-readable `warnings` so the workflow can ask for a better photo before
    posting. Enhancement preserves quality but can't recover detail that was
    never captured."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    w, h = img.size
    key = _pick_aspect(w, h) if aspect == "auto" else aspect
    tw, th = IG_SIZES[key]
    ar = tw / th
    if w / h > ar:
        cw, ch = int(round(h * ar)), h
    else:
        cw, ch = w, int(round(w / ar))
    long_edge = max(cw, ch)

    arr = np.asarray(img)
    blown = float((arr >= 250).all(axis=2).mean())     # pure-white, no detail
    crushed = float((arr <= 5).all(axis=2).mean())      # pure-black
    mean_lum = float((arr @ [0.299, 0.587, 0.114]).mean())

    warnings = []
    if long_edge < 1080:
        warnings.append(
            f"Low resolution — after cropping it's only {cw}x{ch}px (IG ideal "
            f"{tw}x{th}). It may look soft when enlarged. Send a higher-res "
            "original if you have one.")
    if blown > 0.02:
        warnings.append(
            f"Blown-out highlights — {blown*100:.0f}% of the photo is pure "
            "white with no detail. That detail can't be recovered; a "
            "better-exposed shot would look cleaner.")
    if crushed > 0.06:
        warnings.append(
            f"Crushed shadows — {crushed*100:.0f}% of the photo is pure black.")
    if mean_lum < 55:
        warnings.append(
            "Very dark photo — we'll brighten it, but a better-lit original "
            "will look crisper and less grainy.")
    return {"width": w, "height": h, "crop": [cw, ch], "long_edge": long_edge,
            "blown_fraction": blown, "crushed_fraction": crushed,
            "mean_lum": mean_lum, "ok": not warnings, "warnings": warnings}


def adjust(img: Image.Image, *, brightness: float = 1.0, contrast: float = 1.0,
          color: float = 1.0, sharpen: float = 0.0) -> Image.Image:
    """Apply targeted, explicit tweaks on top of the base enhance — used when an
    approver asks for a specific fix ('too dark', 'more punch', 'less saturated').
    Multipliers: 1.0 = no change. Bounds are clamped to keep things sane."""
    brightness = min(max(brightness, 0.6), 1.4)
    contrast = min(max(contrast, 0.7), 1.4)
    color = min(max(color, 0.5), 1.5)
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if color != 1.0:
        img = ImageEnhance.Color(img).enhance(color)
    if sharpen > 0:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2,
                                                 percent=int(60 * sharpen),
                                                 threshold=3))
    return img


def process_bytes(data: bytes, *, aspect: str = DEFAULT_ASPECT,
                  intensity: float = 1.0, quality: int = 95,
                  adjust_opts: dict | None = None, zoom: float = 1.0) -> bytes:
    """Full pipeline: enhance lighting, optionally apply targeted tweaks, then
    crop to an IG frame. Returns JPEG bytes at high quality (4:4:4 chroma) so
    fine detail/text stays crisp. aspect: '4:5' | '1:1' | '1.91:1' | 'auto'.
    adjust_opts: optional dict for adjust() (brightness/contrast/color/sharpen).
    zoom>1 crops tighter / more zoomed-in."""
    img = Image.open(io.BytesIO(data))
    img = enhance(img, intensity=intensity)
    if adjust_opts:
        img = adjust(img, **adjust_opts)
    img = fit_for_ig(img, aspect=aspect, zoom=zoom)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True, subsampling=0)
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
