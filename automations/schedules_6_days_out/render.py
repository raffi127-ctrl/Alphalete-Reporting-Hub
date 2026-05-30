"""Render the sorted Schedules table as a good-quality PNG, with each Rep group
shaded its gradient color (same palette the Sheet uses, via colors.py).

Cross-platform fonts: tries common Windows + macOS TrueType paths, then falls
back to PIL's bundled default — no Mac-only hardcoded path (runs on both OSes).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PIL import Image, ImageDraw, ImageFont

from automations.schedules_6_days_out import colors, pull

# Display label + pixel width per column (left→right = Sheet order).
COLS = [
    ("Owner Name", 200),
    ("Rep", 190),
    ("Customer Name", 210),
    ("sp.Customer Phone", 160),
    ("Days to Appointment", 150),
    ("Tech Install", 150),
]

SCALE = 2          # render at 2x for a crisp, high-quality screenshot
ROW_H = 30
HEADER_H = 56
PAD = 12

HEADER_BG = (50, 50, 80)
HEADER_FG = (255, 255, 255)
COLHDR_BG = (70, 70, 90)
GRID = (210, 210, 210)

# Font candidates in preference order — first that loads wins.
_REG = ["arial.ttf", "Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "DejaVuSans.ttf"]
_BOLD = ["arialbd.ttf", "Arial Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf",
         "DejaVuSans-Bold.ttf"]


def _font(size: int, bold: bool = False):
    for name in (_BOLD if bold else _REG):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_color(bg01) -> tuple:
    """Always black — the spec calls for black text, and every palette shade is
    kept pastel/light enough to stay legible under it."""
    return (0, 0, 0)


def _sorted_for_color(rows: List[Dict[str, str]], color_by: str
                      ) -> List[Dict[str, str]]:
    """Sort so each color group is one contiguous block and the gradient runs
    top→bottom: primary = the color key, secondary = Rep, tertiary = Customer."""
    return sorted(
        rows,
        key=lambda d: (d.get(color_by, "").strip().casefold(),
                       d.get("Rep", "").strip().casefold(),
                       d.get("Customer Name", "").strip().casefold()),
    )


def render(rows: List[Dict[str, str]], out_path: Path, title: str,
           color_by: str = "Owner Name", palette: Dict[str, tuple] = None
           ) -> Path:
    """Render the table as a PNG, shading each `color_by` group its color.
    Full-captainship tables color by 'Owner Name'; the single-owner (Rafael
    Hidalgo) Slack image colors by 'Rep'. Rows are re-sorted by the color key
    so groups are contiguous.

    palette: optional {group_value: (r,g,b) in 0..1}. If omitted, falls back to
    the simple ascending gradient."""
    s = SCALE
    cols = COLS
    rows = _sorted_for_color(rows, color_by)
    total_w = (sum(w for _, w in cols) + PAD * 2) * s
    body_rows = max(len(rows), 1)
    h = (HEADER_H + ROW_H * (body_rows + 1) + PAD * 2) * s

    img = Image.new("RGB", (total_w, h), "white")
    draw = ImageDraw.Draw(img)
    font = _font(13 * s)
    bold = _font(13 * s, bold=True)
    title_font = _font(16 * s, bold=True)

    x, y = PAD * s, PAD * s
    inner_w = total_w - PAD * 2 * s

    # Title bar.
    draw.rectangle([x, y, x + inner_w, y + HEADER_H * s], fill=HEADER_BG)
    draw.text((x + 10 * s, y + 7 * s), title, fill=HEADER_FG, font=title_font)
    draw.text((x + 10 * s, y + 32 * s), f"{len(rows)} row(s)",
              fill=HEADER_FG, font=font)
    y += HEADER_H * s

    # Column header.
    cx = x
    for col_name, w in cols:
        draw.rectangle([cx, y, cx + w * s, y + ROW_H * s], fill=COLHDR_BG)
        draw.text((cx + 5 * s, y + 6 * s), col_name, fill="white", font=bold)
        cx += w * s
    y += ROW_H * s

    if not rows:
        draw.text((x + 10 * s, y + 6 * s), "No scheduled installs 6+ days out.",
                  fill=(120, 120, 120), font=font)
        img.save(out_path)
        return out_path

    group_color = palette or colors.family_palette(
        [r.get(color_by, "") for r in rows])
    for row in rows:
        c01 = group_color[row.get(color_by, "")]
        bg = colors.rgb01_to_255(c01)
        fg = _text_color(c01)
        draw.rectangle([x, y, x + inner_w, y + ROW_H * s], fill=bg)
        cx = x
        for col_name, w in cols:
            val = (row.get(col_name, "") or "")[:34]
            draw.text((cx + 5 * s, y + 6 * s), val, fill=fg, font=font)
            draw.line([cx, y, cx, y + ROW_H * s], fill=GRID)  # column separator
            cx += w * s
        draw.line([x, y, x + inner_w, y], fill=GRID)          # row separator
        y += ROW_H * s

    img.save(out_path)
    return out_path
