"""The payout image posted to Slack — two week tables, side by side.

Deliberately the same look as `automations/rep_activations/render.py` (the
Fiber one): same column set, same color bands, same 2x supersample. A rep
seeing both in Slack should not have to learn two layouts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

SCALE = 2                 # render at 2x, downsample with LANCZOS

# Pre-scaled once, so measuring and drawing can never disagree about units.
TITLE_H = 28 * SCALE
HEADER_H = 24 * SCALE
ROW_H = 22 * SCALE
PAD = 14 * SCALE
GAP = 30 * SCALE
CELL_PAD = 7 * SCALE
MIN_REP_W = 170 * SCALE
NUM_W = 74 * SCALE

# "Paid" and "Cancelled" are THIS WEEK. "Still Open" is not a week figure —
# it's every deal not yet accepted, and it reads the same in both tables. No
# Total column: adding a week number to an all-time one meant nothing, and it
# was the source of a real misreading (Carlos, 2026-07-18).
# NOT "Paid" — Carlos, 2026-07-18: "I read 'paid' and I would think I've
# already gotten paid on it, but I'm not getting paid on it until next week."
# Acceptance is the event; the money follows later.
COLS: List[Tuple[str, str, str]] = [
    ("Rep Name", "rep", "left"),
    ("Accepted by Supplier", "posted", "center"),
    ("Cancelled", "canceled", "center"),
    ("Still Open", "pending", "center"),
]

# (min PAID inclusive, RGB) — first match wins, high to low. Keyed on what
# pays that week, which is what the row is ranked by.
BANDS = [
    (8, (169, 208, 142)),
    (5, (159, 227, 240)),
    (3, (255, 229, 153)),
    (1, (217, 217, 217)),
    (0, (234, 153, 153)),
]
HEADER_BG = (242, 242, 242)
GRID = (0, 0, 0)
TEXT = (0, 0, 0)
WHITE = (255, 255, 255)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _band(total: int) -> Tuple[int, int, int]:
    for floor, rgb in BANDS:
        if total >= floor:
            return rgb
    return WHITE


def _text_w(draw, text, font) -> int:
    return int(draw.textlength(str(text), font=font))


def _col_widths(draw, rows, font, head_font) -> List[int]:
    """Width per column, sized to its own header and values.

    Was a flat NUM_W for every numeric column, which clipped a long header
    the moment "Paid" became "Accepted by Supplier".
    """
    widths = []
    for i, (head, key, _align) in enumerate(COLS):
        w = _text_w(draw, head, head_font) + 2 * CELL_PAD
        for r in rows:
            w = max(w, _text_w(draw, r[key], font) + 2 * CELL_PAD)
        if i == 0:
            w = max(w, MIN_REP_W)
        else:
            w = max(w, NUM_W)
        widths.append(int(w))
    return widths


def _table_width(draw, rows, font, head_font) -> int:
    widths = _col_widths(draw, rows, font, head_font)
    return sum(widths), widths


def _draw_table(draw, x: int, y: int, title: str, rows: Sequence[Dict],
                fonts) -> int:
    f_title, f_head, f_cell = fonts
    total_w, widths = _table_width(draw, rows, f_cell, f_head)

    draw.text((x, y), title, font=f_title, fill=TEXT)
    y += TITLE_H

    cx = x
    for (head, _key, _align), w in zip(COLS, widths):
        draw.rectangle([cx, y, cx + w, y + HEADER_H], fill=HEADER_BG, outline=GRID)
        tw = _text_w(draw, head, f_head)
        draw.text((cx + (w - tw) / 2, y + 5 * SCALE), head, font=f_head, fill=TEXT)
        cx += w
    y += HEADER_H

    for r in rows:
        fill = _band(r["posted"])
        cx = x
        for (_head, key, align), w in zip(COLS, widths):
            draw.rectangle([cx, y, cx + w, y + ROW_H], fill=fill, outline=GRID)
            val = str(r[key])
            if align == "left":
                draw.text((cx + CELL_PAD, y + 4 * SCALE), val, font=f_cell, fill=TEXT)
            else:
                tw = _text_w(draw, val, f_cell)
                draw.text((cx + (w - tw) / 2, y + 4 * SCALE), val, font=f_cell, fill=TEXT)
            cx += w
        y += ROW_H

    # TOTAL strip
    cx = x
    sums = {k: sum(r[k] for r in rows) for _h, k, _a in COLS if k != "rep"}
    for (_head, key, align), w in zip(COLS, widths):
        draw.rectangle([cx, y, cx + w, y + ROW_H], fill=HEADER_BG, outline=GRID)
        val = "TOTAL" if key == "rep" else str(sums[key])
        if align == "left":
            draw.text((cx + CELL_PAD, y + 4 * SCALE), val, font=_font(13 * SCALE, True),
                      fill=TEXT)
        else:
            f = _font(13 * SCALE, True)
            tw = _text_w(draw, val, f)
            draw.text((cx + (w - tw) / 2, y + 4 * SCALE), val, font=f, fill=TEXT)
        cx += w
    return total_w


def render(tables: Dict, out_path: Path, *, subtitle: str = "") -> Path:
    """Draw both week tables and save the PNG."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fonts = (_font(15 * SCALE, True), _font(12 * SCALE, True),
             _font(13 * SCALE, False))

    # Measure on a scratch canvas first.
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    last, this = tables["last"], tables["this"]
    w_last, _ = _table_width(probe, last["rows"], fonts[2], fonts[1])
    w_this, _ = _table_width(probe, this["rows"], fonts[2], fonts[1])
    rows_h = max(len(last["rows"]), len(this["rows"])) + 1     # +1 TOTAL strip

    sub_h = 26 * SCALE if subtitle else 0
    W = PAD * 2 + w_last + GAP + w_this
    H = PAD * 2 + sub_h + TITLE_H + HEADER_H + rows_h * ROW_H

    img = Image.new("RGB", (int(W), int(H)), WHITE)
    draw = ImageDraw.Draw(img)

    y0 = PAD
    if subtitle:
        draw.text((PAD, y0), subtitle, font=fonts[1], fill=(110, 110, 110))
        y0 += sub_h

    _draw_table(draw, PAD, y0,
                "LAST WEEK  ({})".format(last["label"]), last["rows"], fonts)
    _draw_table(draw, PAD + w_last + GAP, y0,
                "THIS WEEK  ({})".format(this["label"]), this["rows"], fonts)

    img = img.resize((int(W / SCALE), int(H / SCALE)), Image.LANCZOS)
    img.save(out_path)
    return out_path
