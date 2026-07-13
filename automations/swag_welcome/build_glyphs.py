"""One-time build tool: turn Megan's handwriting-sample photo into a glyph
library (one transparent PNG per letter, made of her REAL ink strokes) that
compose.py stamps to spell names.

Source: resources/swag/handwriting-raw.png — Megan's 4032px sample sheet, four
alphabets (upper + lower). We use the two cleanest complete sets: uppercase
A–Z from sample-3's two lines, lowercase a–z from sample-4's two lines. A font
reads as type even with jitter, so we stamp real strokes instead.

Run:  .venv/bin/python -m automations.swag_welcome.build_glyphs
Output: resources/swag/glyphs/{upper,lower}/<letter>.png + metrics.json
        + _debug/ montages for verification.
"""

from __future__ import annotations

import json
import string
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageFilter, ImageDraw, ImageFont

RES = Path(__file__).resolve().parents[2] / "resources" / "swag"
RAW = RES / "handwriting-raw.png"
DBG = RES / "glyphs" / "_debug"

CROP = (300, 340, 2900, 2400)   # writing region (excludes margins + the thumb)
INK_THR = 185                   # after illumination normalization
ROW_FRAC = 0.06
SPLIT_MIN_H = 190               # bands taller than this are two merged lines
MERGE_GAP = 45
COL_GAP = 14                    # blank cols wider than this separate letters
MIN_LETTER_W = 12
GLYPH_INK = (24, 28, 46)

# Verified (line, segment) → letter maps (see the contact sheet in git history).
# Uppercase: sample-3 lines 4,5. Lowercase: sample-4 lines 6 (a–p) and 7 (q–z,
# whose stray tail marks 7.7/7.10/7.12 are skipped; x/y/z are 7.8/7.9/7.11).
_UP = list(string.ascii_uppercase)
MAP_UPPER = {L: (4, i) for i, L in enumerate(_UP[:12])}
MAP_UPPER.update({L: (5, i) for i, L in enumerate(_UP[12:])})
MAP_LOWER = {L: (6, i) for i, L in enumerate(string.ascii_lowercase[:16])}
MAP_LOWER.update({L: (7, s) for L, s in
                  {"q": 0, "r": 1, "s": 2, "t": 3, "u": 4, "v": 5, "w": 6,
                   "x": 8, "y": 9, "z": 11}.items()})


def _load_norm() -> np.ndarray:
    im = ImageOps.exif_transpose(Image.open(RAW)).convert("L").crop(CROP)
    bg = im.filter(ImageFilter.GaussianBlur(50))
    a = np.asarray(im).astype(np.float32)
    b = np.asarray(bg).astype(np.float32)
    return np.clip((a / (b + 1e-3)) * 255, 0, 255)


def _bands(mask: np.ndarray) -> list[tuple[int, int]]:
    proj = mask.sum(axis=1)
    on = proj > proj.max() * ROW_FRAC
    raw = []
    s = None
    for i, v in enumerate(on):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s > 25:
                raw.append((s, i))
            s = None
    if s is not None:
        raw.append((s, len(on)))
    merged = []
    for b in raw:
        if merged and b[0] - merged[-1][1] < MERGE_GAP:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)
    out = []
    for s, e in merged:
        if e - s > SPLIT_MIN_H:
            sub = proj[s:e]
            q = len(sub) // 4
            valley = q + int(np.argmin(sub[q:len(sub) // 2 + q]))
            out.append((s, s + valley))
            out.append((s + valley, e))
        else:
            out.append((s, e))
    return out


def _letters(mask: np.ndarray, band: tuple[int, int]) -> list[tuple[int, int]]:
    y0, y1 = band
    proj = mask[y0:y1].sum(axis=0)
    on = proj > 0
    segs = []
    s = None
    gap = 0
    for i, v in enumerate(on):
        if v:
            if s is None:
                s = i
            gap = 0
        elif s is not None:
            gap += 1
            if gap >= COL_GAP:
                if (i - gap) - s >= MIN_LETTER_W:
                    segs.append((s, i - gap))
                s = None
                gap = 0
    if s is not None:
        segs.append((s, len(on)))
    return segs


def _vbounds(mask, band, seg) -> tuple[int, int]:
    sub = mask[band[0]:band[1], seg[0]:seg[1]]
    ys = np.where(sub.any(axis=1))[0]
    return int(ys[0]), int(ys[-1])


DESC_MARGIN = 110  # px to look below the band for a letter's descender loop
X_MARGIN = 55      # px to look left/right — descender loops/hooks (g/y/j) curl
                   # OUT well past the letter's own column; connectivity keeps
                   # neighbors out (they're separated by a gap)
CAPTURE_THR = 205  # slightly looser than INK_THR so thin loop edges survive


def _extract(norm, mask, band, seg) -> tuple[Image.Image, int, int]:
    """Cut one letter as RGBA, capturing its full descender. The line bands end
    near the baseline (descenders have too little ink to survive the row
    threshold), so we look DESC_MARGIN px lower and keep only ink that is
    connected (flood-filled) to the letter's body — the next line, separated by
    a gap, isn't grabbed. Returns (image, true_top_abs, true_bottom_abs)."""
    from collections import deque
    y0, y1 = band
    y1e = min(mask.shape[0], y1 + DESC_MARGIN)
    x0, x1 = seg
    xa = max(0, x0 - X_MARGIN)
    xb = min(mask.shape[1], x1 + X_MARGIN)
    # Flood over a LOOSER capture threshold, in a window widened left/right so a
    # descender loop that curls past the letter's column is followed. Seed only
    # from the SOLID body (main mask) so we don't start from paper noise; a gap
    # to any neighbour keeps that neighbour out.
    sub = norm[y0:y1e, xa:xb] < CAPTURE_THR
    keep = np.zeros_like(sub)
    dq = deque()
    dx = x0 - xa                  # body's column offset inside the window
    for r, c in np.argwhere(mask[y0:y1, x0:x1]):
        if not keep[r, c + dx]:
            keep[r, c + dx] = True
            dq.append((int(r), int(c + dx)))
    H, W = sub.shape
    while dq:
        r, c = dq.popleft()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = r + dr, c + dc
                if 0 <= nr < H and 0 <= nc < W and sub[nr, nc] and not keep[nr, nc]:
                    keep[nr, nc] = True
                    dq.append((nr, nc))
    ys = np.where(keep.any(axis=1))[0]
    xs = np.where(keep.any(axis=0))[0]
    t, b = int(ys[0]), int(ys[-1])
    l, r = int(xs[0]), int(xs[-1])
    sub_norm = norm[y0 + t:y0 + b + 1, xa + l:xa + r + 1]
    sub_keep = keep[t:b + 1, l:r + 1]
    cov = np.clip((235.0 - sub_norm) / (235.0 - 130.0) * 255.0, 0, 255).astype(np.uint8)
    cov[~sub_keep] = 0            # drop any stray ink not part of this letter
    h, w = cov.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = GLYPH_INK
    rgba[..., 3] = cov
    return Image.fromarray(rgba, "RGBA"), y0 + t, y0 + b


def main():
    norm = _load_norm()
    mask = norm < INK_THR
    bands = _bands(mask)
    print(f"lines: {len(bands)}")
    line_segs = {k: _letters(mask, bd) for k, bd in enumerate(bands)}
    # Baseline in ABSOLUTE (crop) y, to match _extract's returned bounds.
    baselines = {k: (bands[k][0] + float(np.median([_vbounds(mask, bands[k], s)[1] for s in segs]))
                     if segs else 0.0) for k, segs in line_segs.items()}

    out_u = RES / "glyphs" / "upper"
    out_l = RES / "glyphs" / "lower"
    for d in (out_u, out_l, DBG):
        d.mkdir(parents=True, exist_ok=True)

    metrics, saved = {}, []

    def _do(mapping, outdir, tag):
        for letter, (line, si) in mapping.items():
            segs = line_segs.get(line, [])
            if si >= len(segs):
                print(f"  !! {tag}:{letter} seg {line}.{si} missing")
                continue
            g, top, bot = _extract(norm, mask, bands[line], segs[si])
            g.save(outdir / f"{letter}.png")
            base = baselines[line]
            metrics[f"{tag}:{letter}"] = {"w": g.width, "h": g.height,
                                          "asc": round(base - top, 1),
                                          "desc": round(bot - base, 1)}
            saved.append((tag, letter, g))

    _do(MAP_UPPER, out_u, "U")
    _do(MAP_LOWER, out_l, "l")
    (RES / "glyphs" / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(f"saved {len(saved)} glyphs + metrics")

    cell, cols = 130, 13
    rows = (len(saved) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    try:
        fnt = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 20)
    except Exception:
        fnt = ImageFont.load_default()
    for i, (tag, letter, g) in enumerate(saved):
        r, c = divmod(i, cols)
        t = g.copy()
        t.thumbnail((cell - 30, cell - 40))
        bgc = Image.new("RGB", (cell, cell), (255, 255, 255))
        bgc.paste(t, (15, 25), t)
        sheet.paste(bgc, (c * cell, r * cell))
        d.text((c * cell + 4, r * cell + 2), f"{tag}:{letter}", fill=(200, 0, 0), font=fnt)
    sheet.save(DBG / "glyphs_check.png")
    print("verify ->", DBG / "glyphs_check.png")


if __name__ == "__main__":
    main()
