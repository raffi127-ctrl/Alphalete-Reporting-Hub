"""Wireless tier pay legend, drawn ON TOP of every Wireless Churn bucket image.

Rafael, #l10-alphalete 2026-11-12 ("Fiber Captainship email - Wireless tier
Bonuses"): show the 0-30 Day and the 90 Day churn tier buckets, and under them
how much the port-line pay goes up or down for each combined tier. Wireless pay
is set by BOTH tiers together ("0-30 tier - 90 tier"), and 3-3 is the baseline.
Eve 2026-11-12: tiers on top, the churn board under them, on every bucket.

Source: the three screenshots Raf posted in that thread (SCI comp sheet):
0-30 Day buckets, 90-Day buckets, and the Port Line Commission per combined
tier (1-1 $103 ... 4-4 $193). The $ change is that commission minus 3-3's.
When SCI changes the plan, update the three tables below — nothing else.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from PIL import Image, ImageDraw

from automations.new_internet_churn.render import _font

# Tier -> churn range, as printed on the SCI sheet.
TIERS_0_30 = {1: "8.01%+", 2: "5.21% - 8.00%", 3: "2.41% - 5.20%", 4: "2.40% & lower"}
TIERS_90 = {1: "15.01%+", 2: "12.01% - 15%", 3: "9.01% - 12%", 4: "9% or lower"}

# (0-30 tier, 90 tier) -> Port Line Commission ($ per port line).
PORT_LINE_PAY: Dict[Tuple[int, int], int] = {
    (1, 1): 103, (1, 2): 113, (1, 3): 123, (1, 4): 133,
    (2, 1): 128, (2, 2): 138, (2, 3): 148, (2, 4): 158,
    (3, 1): 153, (3, 2): 163, (3, 3): 173, (3, 4): 183,
    (4, 1): 163, (4, 2): 173, (4, 3): 183, (4, 4): 193,
}
BASELINE = (3, 3)

# Look — taupe gray, NOT the Wireless blue (Eve 2026-11-12: the tiers band must
# not blend into the churn board under it).
HDR_BG = (110, 98, 88)       # dark taupe
HDR_FG = (255, 255, 255)
SUB_BG = (205, 196, 186)     # light taupe
TEXT = (40, 40, 40)
GRID = (190, 190, 190)
UP = (147, 196, 125)        # same green/red as the churn cells
DOWN = (224, 102, 102)
DOWN_SOFT = (240, 170, 170)
BASE_BG = (255, 205, 40)    # the gold of the Wireless goal band
EVEN = (235, 235, 235)

PAD = 12
ROW = 26
GAP = 24


def delta(t030: int, t90: int) -> int:
    """$ per port line vs the 3-3 baseline (negative = less pay)."""
    return PORT_LINE_PAY[(t030, t90)] - PORT_LINE_PAY[BASELINE]


def delta_label(t030: int, t90: int) -> str:
    if (t030, t90) == BASELINE:
        return "BASE"
    v = delta(t030, t90)
    if v == 0:
        return "$0"
    return f"+${v}" if v > 0 else f"-${-v}"


def _cell_bg(t030: int, t90: int):
    if (t030, t90) == BASELINE:
        return BASE_BG
    v = delta(t030, t90)
    if v > 0:
        return UP
    if v == 0:
        return EVEN
    return DOWN if v <= -40 else DOWN_SOFT


def _center(d, box, text, font, fill=TEXT):
    x0, y0, x1, y1 = box
    tw = d.textlength(text, font=font)
    d.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - font.size) / 2 - 1),
           text, fill=fill, font=font)


def _tier_table(d, x, y, title, tiers, w_tier=70, w_rng=130):
    """Two-column 'Tier | churn' table. Returns its (width, height)."""
    f11b, f12b = _font(11, bold=True), _font(12, bold=True)
    w = w_tier + w_rng
    d.rectangle([x, y, x + w, y + ROW], fill=SUB_BG, outline=GRID)
    _center(d, (x, y, x + w, y + ROW), title, f12b)
    yy = y + ROW
    for t, rng in tiers.items():
        d.rectangle([x, yy, x + w_tier, yy + ROW], fill="white", outline=GRID)
        d.rectangle([x + w_tier, yy, x + w, yy + ROW], fill="white", outline=GRID)
        _center(d, (x, yy, x + w_tier, yy + ROW), f"Tier {t}", f11b)
        _center(d, (x + w_tier, yy, x + w, yy + ROW), rng, f11b)
        yy += ROW
    return w, yy - y


def _pay_grid(d, x, y, w_lbl=110, w_cell=70):
    """4x4 grid: rows = 0-30 tier, cols = 90 tier, cell = $ vs 3-3."""
    f11b, f12b = _font(11, bold=True), _font(12, bold=True)
    w = w_lbl + w_cell * 4
    d.rectangle([x, y, x + w, y + ROW], fill=SUB_BG, outline=GRID)
    _center(d, (x, y, x + w, y + ROW), "Pay change per port line (0-30 tier - 90 tier)", f12b)
    yy = y + ROW
    d.rectangle([x, yy, x + w_lbl, yy + ROW], fill=EVEN, outline=GRID)
    _center(d, (x, yy, x + w_lbl, yy + ROW), "0-30 \\ 90 Day", f11b)
    for c in range(1, 5):
        cx = x + w_lbl + w_cell * (c - 1)
        d.rectangle([cx, yy, cx + w_cell, yy + ROW], fill=EVEN, outline=GRID)
        _center(d, (cx, yy, cx + w_cell, yy + ROW), f"Tier {c}", f11b)
    yy += ROW
    for r in range(1, 5):
        d.rectangle([x, yy, x + w_lbl, yy + ROW], fill=EVEN, outline=GRID)
        _center(d, (x, yy, x + w_lbl, yy + ROW), f"Tier {r}", f11b)
        for c in range(1, 5):
            cx = x + w_lbl + w_cell * (c - 1)
            d.rectangle([cx, yy, cx + w_cell, yy + ROW],
                        fill=_cell_bg(r, c), outline=GRID)
            _center(d, (cx, yy, cx + w_cell, yy + ROW), delta_label(r, c), f12b)
        yy += ROW
    return w, yy - y


def draw(width: int) -> Image.Image:
    """The legend as its own image, at least `width` wide."""
    f14b, f11 = _font(14, bold=True), _font(11)
    # Lay out once on a scratch canvas to learn the size.
    t_w, t_h = 200, ROW * 5
    g_w, g_h = 390, ROW * 6
    content_w = t_w * 2 + g_w + GAP * 2
    w = max(width, content_w + PAD * 2)
    title_h = 30
    note_h = 22
    h = PAD + title_h + 10 + max(t_h, g_h) + note_h + PAD
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)

    d.rectangle([PAD, PAD, w - PAD, PAD + title_h], fill=HDR_BG)
    d.text((PAD + 12, PAD + 7), "WIRELESS TIERS — PORT LINE PAY vs 3-3 BASELINE",
           fill=HDR_FG, font=f14b)
    y = PAD + title_h + 10
    x = PAD + max(0, (w - PAD * 2 - content_w) // 2)
    _tier_table(d, x, y, "0-30 Day Churn", TIERS_0_30)
    x += t_w + GAP
    _tier_table(d, x, y, "90 Day Churn", TIERS_90)
    x += t_w + GAP
    _pay_grid(d, x, y)
    base = PORT_LINE_PAY[BASELINE]
    note = (f"Tier 3-3 = baseline ${base} per port line. "
            f"Example: 0-30 Tier 1 + 90 Day Tier 1 = ${PORT_LINE_PAY[(1, 1)]} ({delta_label(1, 1)}).")
    d.text((PAD + 12, y + max(t_h, g_h) + 5), note, fill=TEXT, font=f11)
    return img


def add_to(png: Path) -> Path:
    """Put the legend ABOVE the board at `png` (rewritten in place)."""
    board = Image.open(png).convert("RGB")
    legend = draw(board.width)
    w = max(board.width, legend.width)
    out = Image.new("RGB", (w, legend.height + board.height), "white")
    out.paste(legend, (0, 0))
    out.paste(board, (0, legend.height))
    out.save(png)
    return png
