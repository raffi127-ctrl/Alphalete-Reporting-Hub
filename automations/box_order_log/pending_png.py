"""The Pending Orders worklist as an image, for Slack.

Carlos, 2026-08-25: "can this be a separate screenshot that gets sent please.
we can call it pending orders. its a screenshot from the pending orders tab on
the box order log spreadsheet." So this is deliberately the SAME thing as the
workbook tab, not a summary of it — same columns, same two sections, same
per-rep bands, same status colors — drawn so nobody has to open the xlsx to
see what's still open.

Both surfaces read `pending.build()`, so the tab and this image can't drift.
Drawing conventions (2x supersample, Arial, black grid) come from png.py, the
payout image that ships in the same thread.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from . import clean, pending
from .png import SCALE, _font, _text_w

TITLE_H = 26 * SCALE
SUB_H = 20 * SCALE
BANNER_H = 26 * SCALE
HEADER_H = 24 * SCALE
ROW_H = 21 * SCALE
BAND_H = 22 * SCALE
GAP_H = 10 * SCALE            # the blank line the tab leaves between reps
SECTION_GAP = 18 * SCALE
PAD = 14 * SCALE
CELL_PAD = 7 * SCALE

# Same three fills the workbook uses, so the image and the tab look like one
# document (xlsx.WEEK_BG / HEADER_BG / REP_BG).
BANNER_BG = (0x25, 0x63, 0xEB)
HEADER_BG = (0x43, 0x43, 0x43)
BAND_BG = (0xED, 0xED, 0xED)
GRID = (0, 0, 0)
TEXT = (0, 0, 0)
WHITE = (255, 255, 255)
MUTED = (110, 110, 110)

# Which columns hang left. Everything else centers — matches the tab's
# alignment (cells 1, 4 and 7 are LEFT there).
LEFT_COLS = {"Rep Name", "Business Name", "Next step"}
MIN_W = {"Rep Name": 150, "Business Name": 190, "Next step": 230}
# Business names run long in this data ("Mariscos el puerto de acapulco"); the
# tab can be widened by hand, an image can't, so cap and ellipsize instead of
# letting one row set the width of the whole board.
MAX_CHARS = {"Business Name": 34, "Next step": 46}


def _fsize(font) -> int:
    """Point size for vertical centring.

    PIL's last-resort bitmap font (what _font() falls back to when no TrueType
    is installed) has no .size on older Pillow, and a missing attribute here
    would take the whole 7am run down over a font.
    """
    return int(getattr(font, "size", 11 * SCALE))


def _rgb(hex_str: str) -> Optional[Tuple[int, int, int]]:
    if not hex_str:
        return None
    return tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))


def _cells(s, today: dt.date) -> List[str]:
    """One row's text, in pending.COLUMNS order."""
    out = []
    for col, val in zip(pending.COLUMNS, pending.row_values(s, today)):
        if col == "Sale Date":
            text = val.strftime("%m/%d/%Y") if isinstance(val, dt.date) else ""
        else:
            text = "" if val == "" else str(val)
        cap = MAX_CHARS.get(col)
        if cap and len(text) > cap:
            text = text[:cap - 1] + "…"
        out.append(text)
    return out


def _col_widths(draw, work: Dict, fonts) -> List[int]:
    _f_title, f_head, f_cell = fonts
    widths = []
    for i, col in enumerate(pending.COLUMNS):
        w = _text_w(draw, col, f_head) + 2 * CELL_PAD
        for section in work["sections"]:
            for s in section["rows"]:
                w = max(w, _text_w(draw, _cells(s, work["today"])[i], f_cell)
                        + 2 * CELL_PAD)
        widths.append(int(max(w, MIN_W.get(col, 70) * SCALE)))
    return widths


def _height(work: Dict) -> int:
    h = PAD * 2 + TITLE_H + SUB_H
    if not work["count"]:
        return h + ROW_H
    for section in work["sections"]:
        h += (BANNER_H if section.get("title") else 0) + HEADER_H + SECTION_GAP
        if not section["rows"]:
            h += ROW_H
            continue
        for _rep, rep_rows in section["reps"]:
            h += BAND_H + len(rep_rows) * ROW_H + GAP_H
    return h


def _full_row(draw, x, y, w, h, fill, text, font, color=TEXT, center=False):
    draw.rectangle([x, y, x + w, y + h], fill=fill, outline=GRID)
    tx = x + (w - _text_w(draw, text, font)) / 2 if center else x + CELL_PAD
    draw.text((tx, y + (h - _fsize(font)) / 2 - 1 * SCALE), text, font=font,
              fill=color)
    return y + h


def _draw_section(draw, x, y, section, widths, work, fonts) -> int:
    _f_title, f_head, f_cell = fonts
    f_band = _font(12 * SCALE, True)
    total_w = sum(widths)

    if section.get("title"):
        y = _full_row(draw, x, y, total_w, BANNER_H, BANNER_BG,
                      section["title"], f_head, color=WHITE, center=True)

    cx = x
    for col, w in zip(pending.COLUMNS, widths):
        draw.rectangle([cx, y, cx + w, y + HEADER_H], fill=HEADER_BG,
                       outline=GRID)
        draw.text((cx + (w - _text_w(draw, col, f_head)) / 2,
                   y + (HEADER_H - _fsize(f_head)) / 2 - 1 * SCALE), col,
                  font=f_head, fill=WHITE)
        cx += w
    y += HEADER_H

    if not section["rows"]:
        y = _full_row(draw, x, y, total_w, ROW_H, WHITE, section["empty_note"],
                      f_cell, color=MUTED)
        return y + SECTION_GAP

    for rep, rep_rows in section["reps"]:
        y = _full_row(draw, x, y, total_w, BAND_H, BAND_BG,
                      "{}  •  {} order{}".format(rep, len(rep_rows),
                                                 pending.plural(len(rep_rows))),
                      f_band)
        for s in rep_rows:
            fill = _rgb(clean.color_for(s.status, s.history)) or WHITE
            cx = x
            for col, w, text in zip(pending.COLUMNS, widths,
                                    _cells(s, work["today"])):
                draw.rectangle([cx, y, cx + w, y + ROW_H], fill=fill,
                               outline=GRID)
                tx = (cx + CELL_PAD if col in LEFT_COLS
                      else cx + (w - _text_w(draw, text, f_cell)) / 2)
                draw.text((tx, y + (ROW_H - _fsize(f_cell)) / 2 - 1 * SCALE),
                          text, font=f_cell, fill=TEXT)
                cx += w
            y += ROW_H
        y += GAP_H                       # the tab's blank line between reps
    return y + SECTION_GAP


def render(work: Dict, out_path: Path) -> Path:
    """Draw the whole worklist and save the PNG."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fonts = (_font(15 * SCALE, True), _font(11 * SCALE, True),
             _font(11 * SCALE, False))
    f_title, f_head, f_cell = fonts

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    widths = _col_widths(probe, work, fonts)
    W = PAD * 2 + sum(widths)
    # The subtitle is one long sentence; let it set the width if it has to,
    # rather than running off the edge of the board.
    W = max(W, PAD * 2 + _text_w(probe, work["subtitle"], f_cell))
    H = _height(work)

    img = Image.new("RGB", (int(W), int(H)), WHITE)
    draw = ImageDraw.Draw(img)

    y = PAD
    draw.text((PAD, y), pending.TITLE, font=f_title, fill=TEXT)
    y += TITLE_H
    draw.text((PAD, y), work["subtitle"], font=f_cell, fill=MUTED)
    y += SUB_H

    if not work["count"]:
        draw.text((PAD, y), work["sections"][0]["empty_note"]
                  if len(work["sections"]) == 1
                  else "Nothing pending — every deal is accepted or closed.",
                  font=f_cell, fill=MUTED)
    else:
        for section in work["sections"]:
            y = _draw_section(draw, PAD, y, section, widths, work, fonts)

    img = img.resize((int(W / SCALE), int(H / SCALE)), Image.LANCZOS)
    img.save(out_path)
    return out_path


def build(sales: Sequence, out_path: Path, *,
          today: Optional[dt.date] = None, skip_yellow: bool = True) -> Path:
    """Convenience: model + render in one call.

    Defaults to the yellow-less view because every caller of this is the Slack
    image; pass skip_yellow=False for a picture of the full tab.
    """
    return render(pending.build(sales, today=today, skip_yellow=skip_yellow),
                  out_path)
