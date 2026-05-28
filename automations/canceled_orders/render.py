"""Render Local Office canceled orders as a PNG for the Metrics thread post.
Mirrors the layout Jolie/Eve post manually: 10 cols, blue header bar,
light-blue highlight on new rows."""
from __future__ import annotations

from pathlib import Path
from typing import List, Dict

from PIL import Image, ImageDraw, ImageFont

ROW_H = 26
HEADER_H = 50
PAD = 10

# Display label + min width — order matches Jolie's manual post.
COLS = [
    ("Rep", 140),
    ("Customer Name", 140),
    ("Package", 175),
    ("SPM #", 130),
    ("Order Date", 95),
    ("Install Date", 100),
    ("Status Date", 95),
    ("Customer Phone", 125),
    ("Days to Appointment", 130),
    ("Tech Install", 110),
]

HEADER_BG = (50, 50, 80)
HEADER_FG = (255, 255, 255)
NEW_HIGHLIGHT = (213, 232, 252)


def _font(size: int, bold: bool = False):
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    try:
        return ImageFont.truetype(f"/System/Library/Fonts/Supplemental/{name}", size)
    except Exception:
        return ImageFont.load_default()


def render(rows: List[Dict[str, str]], out_path: Path,
           title: str = "Local Office — Canceled Orders") -> Path:
    cols = COLS
    total_w = sum(w for _, w in cols) + PAD * 2
    h = HEADER_H + ROW_H * (max(len(rows), 1) + 1) + PAD * 2

    img = Image.new("RGB", (total_w, h), "white")
    draw = ImageDraw.Draw(img)
    font = _font(12)
    bold = _font(12, bold=True)
    title_font = _font(14, bold=True)

    x, y = PAD, PAD
    draw.rectangle([x, y, x + total_w - PAD * 2, y + HEADER_H], fill=HEADER_BG)
    draw.text((x + 8, y + 6), title, fill=HEADER_FG, font=title_font)
    draw.text((x + 8, y + 28), f"{len(rows)} row(s)", fill=HEADER_FG, font=font)
    y += HEADER_H

    cx = x
    for col_name, w in cols:
        draw.rectangle([cx, y, cx + w, y + ROW_H], fill=(70, 70, 90))
        draw.text((cx + 4, y + 5), col_name, fill="white", font=bold)
        cx += w
    y += ROW_H

    if not rows:
        draw.text((x + 10, y + 5),
                  "No new Local Office canceled orders.",
                  fill=(120, 120, 120), font=font)
        img.save(out_path)
        return out_path

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
