"""Turn any posted photo into a clean white-background headshot.

Pipeline (all local, no paid API):
  1. Decode the bytes (HEIC included) and honor the EXIF rotation.
  2. Cut the person out with rembg's people-trained model (u2net_human_seg,
     downloads once to ~/.u2net/).
  3. Crop to head-and-shoulders using the cutout mask itself: the top of the
     mask is the head, the first big widening below it is the shoulder flare.
     A full-body dress-code-style photo and a chest-up selfie both land on
     the same framing. If the heuristic can't find a sane crop it falls back
     to fitting the whole person.
  4. Center on a pure-white 1200x1500 canvas with breathing room.

One output: the clean headshot. No name bar — the person's name goes in the
FILENAME only (Megan 2026-08-23, "we don't need names added").

Cross-platform: Pillow + rembg only.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

from automations.headshots import config

_session = None


def _rembg_session():
    global _session
    if _session is None:
        from rembg import new_session
        _session = new_session(config.REMBG_MODEL)
    return _session


def decode(data: bytes) -> Image.Image:
    """Bytes -> upright RGB image (iPhone HEIC + sideways EXIF handled)."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)
    return im.convert("RGB")


def cut_subject(im: Image.Image) -> Image.Image:
    """RGB photo -> RGBA cutout of the person (background alpha = 0)."""
    from rembg import remove
    out = remove(im, session=_rembg_session())
    return out.convert("RGBA")


def _mask_rows(alpha: Image.Image, thresh: int = 40) -> list[tuple[int, int, int]]:
    """Per-row (y, left, right) span of the subject in the alpha channel."""
    import numpy as np
    a = np.asarray(alpha) > thresh
    rows = []
    for y in range(a.shape[0]):
        xs = a[y].nonzero()[0]
        if xs.size:
            rows.append((y, int(xs[0]), int(xs[-1])))
    return rows


def head_shoulders_box(cutout: Image.Image) -> tuple[int, int, int, int] | None:
    """Head-and-shoulders crop box from the subject mask, or None to keep all.

    The head is the top of the mask; scanning down, the shoulder line is the
    first row whose width jumps well past the head's width. Crop ends a bit
    below the shoulders so the frame reads as a badge headshot.
    """
    rows = _mask_rows(cutout.getchannel("A"))
    if len(rows) < 40:
        return None
    top = rows[0][0]
    subj_h = rows[-1][0] - top
    if subj_h <= 0:
        return None

    widths = {y: r - l + 1 for y, l, r in rows}
    ys = sorted(widths)
    # Head width = the widest row in the first 12% of the subject (crown to
    # roughly mid-face). Hair spikes are fine — shoulders are far wider.
    band = [widths[y] for y in ys if y <= top + subj_h * 0.12]
    head_w = max(band) if band else 0
    if head_w <= 0:
        return None

    shoulder_y = None
    for y in ys:
        if y <= top + subj_h * 0.05:
            continue
        if widths[y] >= head_w * 1.55:
            shoulder_y = y
            break
    # No flare found inside the top half -> already a tight face crop (or
    # something odd like a hand up) — keep the whole subject.
    if shoulder_y is None or shoulder_y > top + subj_h * 0.55:
        return None

    head_h = shoulder_y - top
    if head_h < subj_h * 0.04:          # degenerate: flare right at the top
        return None
    bottom = min(rows[-1][0], int(shoulder_y + head_h * 1.05))

    # Horizontal span of what's inside the vertical crop, widened a touch.
    ls = [l for y, l, r in rows if top <= y <= bottom]
    rs = [r for y, l, r in rows if top <= y <= bottom]
    left, right = min(ls), max(rs)
    pad = int((right - left) * 0.06)
    return (max(0, left - pad), top, min(cutout.width, right + pad + 1), bottom)


def compose_clean(cutout: Image.Image) -> Image.Image:
    """Cutout -> the person centered on a pure-white portrait canvas."""
    box = head_shoulders_box(cutout)
    if box:
        cutout = cutout.crop(box)
    else:
        bbox = cutout.getchannel("A").getbbox()
        if bbox:
            cutout = cutout.crop(bbox)

    W, H = config.PHOTO_W, config.PHOTO_H
    margin = config.HEAD_MARGIN
    # Fill the frame TOP to bottom (white margin above the head only), then
    # center the width on the head. Shoulders running off the sides is normal
    # badge framing; empty sky above the head is not.
    avail_h = H * (1 - margin)
    scale = avail_h / cutout.height
    sized = cutout.resize((max(1, round(cutout.width * scale)),
                           max(1, round(cutout.height * scale))),
                          Image.LANCZOS)

    # Head center = midpoint of the mask in the top 15% of the subject.
    rows = _mask_rows(sized.getchannel("A"))
    top_band = [r for r in rows if r[0] <= rows[0][0] + sized.height * 0.15] \
        if rows else []
    head_cx = (sum((l + r) / 2 for _, l, r in top_band) / len(top_band)) \
        if top_band else sized.width / 2

    canvas = Image.new("RGB", (W, H), "white")
    x = round(W / 2 - head_cx)
    x = min(0, max(x, W - sized.width)) if sized.width > W \
        else max(0, min(x, W - sized.width))
    canvas.paste(sized, (x, H - sized.height), sized)
    return canvas


def process(data: bytes) -> Image.Image:
    """Photo bytes -> finished white-background headshot."""
    return compose_clean(cut_subject(decode(data)))
