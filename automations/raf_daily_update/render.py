"""The day's showed rows as a PNG — the same picture the recruiters screenshot
from the sheet (10/13 post): one band of color per status, NO SHOWs left out.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from PIL import Image, ImageDraw, ImageFont

from automations.raf_daily_update import layout as L

COLS = [("Date", "date", 90), ("1st Round", "int1", 190),
        ("2nd Round", "int2", 190), ("First Name", "first", 140),
        ("Last Name", "last", 170), ("Phone", "phone", 140),
        ("Status", "status", 300), ("BOB Date", "bob_date", 90),
        ("Time", "time", 70)]

# (fill, text) per status — the sheet's own conditional-format colors.
COLORS = {
    L.BOB: ("#b7dfc6", "#000000"),
    L.DECLINED: ("#c0472f", "#000000"),
    L.LEADER_NO: ("#4f74c7", "#000000"),
    L.LM: ("#fde68a", "#000000"),
    L.LETTING: ("#f9cb9c", "#000000"),
    L.TO_CALL: ("#ffffff", "#000000"),
}
HEADER_BG, GRID = "#3c3c3c", "#7a7a7a"
ROW_H, PAD = 26, 6

_FONT_PATHS = {
    False: ["/System/Library/Fonts/Supplemental/Georgia.ttf",
            "C:/Windows/Fonts/georgia.ttf"],
    True: ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
           "C:/Windows/Fonts/georgiab.ttf"],
}


def _font(size: int, bold: bool = False):
    for p in _FONT_PATHS[bold]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def _fit(draw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "\u2026", font=font) > width:
        text = text[:-1]
    return text + "\u2026"


def render(rows: List[dict], out: Path, title: str) -> Path:
    shown = [r for r in rows if r["status"] != L.NO_SHOW]
    width = sum(w for _, _, w in COLS)
    height = ROW_H * (len(shown) + 2)
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f, fb = _font(14), _font(14, bold=True)

    d.rectangle([0, 0, width, ROW_H], fill="#1f3fd1")
    d.text((width / 2, ROW_H / 2), title, font=_font(15, True),
           fill="white", anchor="mm")
    y = ROW_H
    x = 0
    d.rectangle([0, y, width, y + ROW_H], fill=HEADER_BG)
    for label, _, w in COLS:
        d.text((x + w / 2, y + ROW_H / 2), label, font=fb, fill="white",
               anchor="mm")
        x += w
    y += ROW_H
    for r in shown:
        bg, fg = COLORS.get(r["status"], COLORS[L.TO_CALL])
        if r["status"] not in COLORS:
            for k, v in COLORS.items():
                if k and r["status"].lower().startswith(k.lower()):
                    bg, fg = v
                    break
        d.rectangle([0, y, width, y + ROW_H], fill=bg)
        x = 0
        for _, key, w in COLS:
            val = r.get(key, "") or ("To call" if key == "status" else "")
            d.text((x + w / 2, y + ROW_H / 2), _fit(d, val, f, w - 2 * PAD),
                   font=f, fill=fg, anchor="mm")
            d.line([x, y, x, y + ROW_H], fill=GRID)
            x += w
        d.line([0, y, width, y], fill=GRID)
        y += ROW_H
    d.rectangle([0, 0, width - 1, height - 1], outline=GRID)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
