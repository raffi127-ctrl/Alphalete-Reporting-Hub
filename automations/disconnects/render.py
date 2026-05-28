"""Render Local Office disconnects as a PNG for the Metrics thread post."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Dict

from PIL import Image, ImageDraw, ImageFont

ROW_H = 26
HEADER_H = 50
PAD = 10

# Sheet column → display label + min width. Order matches the rendered image.
COLS = [
    ("Rep", 140),
    ("Customer Name", 140),
    ("SPM Number", 130),
    ("Account BAN", 110),
    ("Product Type", 110),
    ("Customer Phone", 130),
    ("Package", 130),
    ("Install Date", 100),
    ("DTR Status", 105),
    ("Status Date", 95),
    ("Eligibility Reason", 145),
    ("Auto Bill Pay", 90),
    ("Tech Install", 100),
]

# Green palette differentiates the Disconnects image from Canceled Orders
# (blue) at a glance in the Metrics thread — Megan 2026-05-28.
HEADER_BG = (28, 100, 56)        # forest green
HEADER_FG = (255, 255, 255)
ROW_ALT = (245, 252, 247)
NEW_HIGHLIGHT = (216, 240, 220)  # light green — matches the green Hub card


def _font(size: int, bold: bool = False):
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    try:
        return ImageFont.truetype(f"/System/Library/Fonts/Supplemental/{name}", size)
    except Exception:
        return ImageFont.load_default()


def render(rows: List[Dict[str, str]], out_path: Path,
           title: str = "Local Office — New Internet Disconnects") -> Path:
    cols = COLS
    total_w = sum(w for _, w in cols) + PAD * 2
    h = HEADER_H + ROW_H * (max(len(rows), 1) + 1) + PAD * 2

    img = Image.new("RGB", (total_w, h), "white")
    draw = ImageDraw.Draw(img)
    font = _font(12)
    bold = _font(12, bold=True)
    title_font = _font(14, bold=True)

    x, y = PAD, PAD
    # Title bar
    draw.rectangle([x, y, x + total_w - PAD * 2, y + HEADER_H], fill=HEADER_BG)
    draw.text((x + 8, y + 6), title, fill=HEADER_FG, font=title_font)
    draw.text((x + 8, y + 28), f"{len(rows)} row(s)", fill=HEADER_FG, font=font)
    y += HEADER_H

    # Col headers
    cx = x
    for col_name, w in cols:
        draw.rectangle([cx, y, cx + w, y + ROW_H], fill=(70, 70, 90))
        draw.text((cx + 4, y + 5), col_name, fill="white", font=bold)
        cx += w
    y += ROW_H

    if not rows:
        # Empty-state row.
        draw.text((x + 10, y + 5),
                  "No new Local Office disconnects.",
                  fill=(120, 120, 120), font=font)
        img.save(out_path)
        return out_path

    # Data rows.
    for ri, row in enumerate(rows):
        bg = NEW_HIGHLIGHT if ri % 2 == 0 else "white"
        draw.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=bg)
        cx = x
        for col_name, w in cols:
            val = row.get(col_name, "")
            draw.text((cx + 4, y + 5), val[:30], fill="black", font=font)
            cx += w
        y += ROW_H

    img.save(out_path)
    return out_path
