"""Draw the pay-period calendar as a PNG, styled like Raf's
"Activation/Pay Week" sheet: Week Start (Sunday) / Week End (Saturday) /
Pay Date (Friday), banded rows.

    python -m automations.pay_period_office_info.render     # -> output/
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from automations.rep_activations.render import _font

S = 2                       # saved at 2x so it stays sharp when opened in Slack
COL_W = 150
TITLE_H = 40
HEAD_H = 32
ROW_H = 30
PAD = 16
FOOT_H = 30

TITLE_BG = (109, 143, 201)
HEAD_BG = (31, 56, 100)
BAND_BG = (201, 218, 248)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (90, 90, 90)
HEADS = (("Week Start", "Week End", "Pay Date"),
         ("Sunday", "Saturday", "Friday"))


def _md(d: date) -> str:
    return f"{d.month}/{d.day}/{d:%y}"


def render(weeks: list, out_path: Path, updated: date) -> Path:
    width = (PAD * 2 + COL_W * 3) * S
    height = (PAD * 2 + TITLE_H + HEAD_H * 2 + ROW_H * len(weeks)
              + FOOT_H) * S
    img = Image.new("RGB", (width, height), WHITE)
    d = ImageDraw.Draw(img)
    f_title = _font(20 * S, bold=True)
    f_head = _font(17 * S, bold=True)
    f_row = _font(17 * S)
    f_foot = _font(12 * S)
    x0, y = PAD * S, PAD * S

    def cell(x, y, w, h, text, font, bg, fg):
        d.rectangle([x, y, x + w, y + h], fill=bg, outline=BLACK, width=S)
        tw = d.textlength(text, font=font)
        asc, desc = font.getmetrics()
        d.text((x + (w - tw) / 2, y + (h - asc - desc) / 2), text,
               font=font, fill=fg)

    cell(x0, y, COL_W * 3 * S, TITLE_H * S, "Activation/Pay Week",
         f_title, TITLE_BG, BLACK)
    y += TITLE_H * S
    for heads in HEADS:
        for i, h in enumerate(heads):
            cell(x0 + i * COL_W * S, y, COL_W * S, HEAD_H * S, h,
                 f_head, HEAD_BG, WHITE)
        y += HEAD_H * S
    for n, week in enumerate(weeks):
        bg = BAND_BG if n % 2 else WHITE
        for i, day in enumerate(week):
            cell(x0 + i * COL_W * S, y, COL_W * S, ROW_H * S, _md(day),
                 f_row, bg, BLACK)
        y += ROW_H * S
    d.text((x0, y + 8 * S), f"Updated {_md(updated)}", font=f_foot, fill=GRAY)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    from automations.pay_period_office_info.run import build_image
    print(build_image(date.today()))
