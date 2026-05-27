"""Render the Ongoing Cancel image. Output matches the layout Megan signed
off on 2026-05-27: rep rows × 7-day columns, Green/Yellow cell shading."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Layout
ROW_H = 26
HEADER_H = 50
OWNER_COL_W = 160
REP_COL_W = 220
DAY_COL_W = 80
PAD = 10

GREEN = (197, 224, 180)
YELLOW = (255, 230, 153)
RED = (244, 200, 200)
HEADER_BG = (50, 50, 80)
HEADER_FG = (255, 255, 255)
TOTAL_BG = (235, 235, 245)


def _font(size: int, bold: bool = False):
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    try:
        return ImageFont.truetype(f"/System/Library/Fonts/Supplemental/{name}", size)
    except Exception:
        return ImageFont.load_default()


def render(parsed: dict, out_path: Path) -> Path:
    """parsed = output of pull.parse()."""
    days = parsed["days"]
    data_rows = parsed["rows"]
    totals = parsed["grand_total_per_day"]

    w = OWNER_COL_W + REP_COL_W + DAY_COL_W * len(days) + PAD * 2
    # +1 row for the Grand Total summary at the top.
    h = HEADER_H + ROW_H * (len(data_rows) + 1) + PAD * 2

    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    font = _font(13)
    bold = _font(13, bold=True)

    x = PAD
    y = PAD

    # Header.
    draw.rectangle([x, y, x + w - PAD * 2, y + HEADER_H], fill=HEADER_BG)
    draw.text((x + 8, y + HEADER_H // 2 - 8), "Owner", fill=HEADER_FG, font=bold)
    draw.text((x + OWNER_COL_W + 8, y + HEADER_H // 2 - 8), "Rep",
              fill=HEADER_FG, font=bold)
    for i, day in enumerate(days):
        cx = x + OWNER_COL_W + REP_COL_W + DAY_COL_W * i
        try:
            d = datetime.strptime(day, "%m/%d/%Y")
            label = f"{d.strftime('%a')} {d.month}/{d.day}"
        except Exception:
            label = day
        draw.text((cx + 4, y + HEADER_H // 2 - 8), label,
                  fill=HEADER_FG, font=bold)
    y += HEADER_H

    # Grand Total row.
    draw.rectangle([x, y, x + w - PAD * 2, y + ROW_H], fill=TOTAL_BG)
    draw.text((x + 4, y + 4), "Grand Total", fill="black", font=bold)
    for i, day in enumerate(days):
        cx = x + OWNER_COL_W + REP_COL_W + DAY_COL_W * i
        val = totals.get(day, "")
        if val:
            draw.text((cx + 6, y + 4), val, fill="black", font=bold)
    draw.line([x, y + ROW_H, x + w - PAD * 2, y + ROW_H], fill=(180, 180, 200))
    y += ROW_H

    # Per-rep rows.
    prev_owner = None
    for row in data_rows:
        owner, rep = row["owner"], row["rep"]
        if owner != prev_owner:
            draw.text((x + 4, y + 4), owner, fill=(60, 60, 80), font=bold)
            prev_owner = owner
        draw.text((x + OWNER_COL_W + 4, y + 4), rep, fill="black", font=font)
        for i, day in enumerate(days):
            cx = x + OWNER_COL_W + REP_COL_W + DAY_COL_W * i
            val, color = row["per_day"].get(day, ("", ""))
            bg = {"Green": GREEN, "Yellow": YELLOW, "Red": RED}.get(color)
            if bg:
                draw.rectangle([cx, y, cx + DAY_COL_W - 1, y + ROW_H - 1],
                               fill=bg)
            if val:
                draw.text((cx + 6, y + 4), val, fill="black", font=font)
        draw.line([x, y + ROW_H, x + w - PAD * 2, y + ROW_H],
                  fill=(220, 220, 220))
        y += ROW_H

    img.save(out_path)
    return out_path
