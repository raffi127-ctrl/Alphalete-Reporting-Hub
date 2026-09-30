"""Draw the Southshore Org board — the layout Colten approved 2026-09-30."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

NAVY, NAVY2 = (28, 58, 99), (42, 82, 135)
DARK, GOLD = (64, 64, 64), (255, 192, 0)
ROW_A, ROW_B = (255, 255, 255), (242, 242, 242)
WEEKCOL = (221, 232, 245)
RED, GREEN = (244, 199, 206), (198, 239, 206)
BORDER = (170, 170, 170)

_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",   # macOS
    "C:/Windows/Fonts/georgiab.ttf",                          # Windows
]


def _font(size: int):
    for p in _FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise FileNotFoundError("Georgia Bold not found (house font) — "
                            f"looked in {_FONT_PATHS}")


def _pct(now: float, then: Optional[float]) -> str:
    if not then:
        return ""
    return f"{round((now - then) / then * 100):+d}%"


def _fill_for(p: str):
    return GREEN if p.startswith("+") else RED if p.startswith("-") else ROW_A


def _md(d: dt.date) -> str:
    return f"{d.month}.{d.day}"


def render(out_path: Path, *, week: List[dt.date], done: List[dt.date],
           rows: list, history: list, lw_total: Optional[int],
           pw_total: Optional[int], title: str) -> Path:
    """rows: [(display name, [7 day values or None], units, last wk, prev wk)]
    sorted already. history: [(week-ending date, [7 ints] or None)] newest first."""
    org_now = [sum(r[1][i] or 0 for r in rows) if week[i] in done else None
               for i in range(7)]
    n = len(done)
    known = [h for _we, h in history if h]
    last = history[0][1] if history else None
    avg4 = ([sum(h[i] for h in known) / len(known) for i in range(7)]
            if len(known) == 4 else None)
    wtd = sum(v or 0 for v in org_now)

    heads = ["#", "Market Managers"] + [d.strftime("%A") for d in week] + \
            ["Units", "Last Week", "Prev Week"]
    sub = ["", "Units"] + [f"{d.month}/{d.day}" for d in week] + ["", "", ""]
    body = []
    for i, (name, vals, tot, lw, pw) in enumerate(rows, 1):
        fill = ROW_A if i % 2 else ROW_B
        body.append(([str(i), name] + ["" if v is None else str(v) for v in vals] +
                     [str(tot), "" if lw is None else str(lw),
                      "" if pw is None else str(pw)],
                     [fill] * 9 + [WEEKCOL] * 3, "body"))
    body.append((["", "Org Total"] + ["" if v is None else str(v) for v in org_now] +
                 [str(wtd), "" if lw_total is None else str(lw_total),
                  "" if pw_total is None else str(pw_total)], None, "total"))
    for we, h in history:
        body.append((["", f"W.E. {_md(we)}"] +
                     ([str(v) for v in h] if h else [""] * 7) +
                     [str(sum(h)) if h else "", "", ""], None, "hist"))
    for label, base in (("vs Prior Week", last), ("vs 4 Week AVG", avg4)):
        cells, fills = ["", label], [ROW_A, ROW_A]
        for i, d in enumerate(week):
            p = _pct(org_now[i], base[i]) if (base and d in done) else ""
            cells.append(p)
            fills.append(_fill_for(p))
        p = _pct(wtd, sum(base[:n])) if (base and n) else ""
        cells += [p, "", ""]
        fills += [_fill_for(p), ROW_A, ROW_A]
        body.append((cells, fills, "delta"))

    f, ft = _font(26), _font(34)
    widths = [60, 330] + [165] * 7 + [120, 160, 160]
    rh, pad, title_h = 50, 20, 70
    W = sum(widths) + 2 * pad
    H = pad * 2 + title_h + rh * 2 + rh * len(body) + 12
    img = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(img)

    def cell(x, y, w, text, fill, color="black"):
        g.rectangle([x, y, x + w, y + rh], fill=fill, outline=BORDER)
        tw = g.textlength(text, font=f)
        g.text((x + (w - tw) / 2, y + (rh - 30) / 2), text, font=f, fill=color)

    head = f"{title}  |  Week Ending {_md(week[-1])}"
    g.rectangle([pad, pad, W - pad, pad + title_h], fill=NAVY)
    g.text(((W - g.textlength(head, font=ft)) / 2, pad + 14), head, font=ft,
           fill="white")
    y = pad + title_h
    for rowcells, fillc in ((heads, NAVY2), (sub, NAVY)):
        x = pad
        for w, t in zip(widths, rowcells):
            cell(x, y, w, t, fillc, "white")
            x += w
        y += rh
    prev_style = None
    for cells, fills, style in body:
        if style != prev_style and style in ("hist", "delta"):
            y += 6                                   # a gap between the blocks
        prev_style = style
        x = pad
        for i, (w, t) in enumerate(zip(widths, cells)):
            if style in ("total", "hist"):
                cell(x, y, w, t, DARK, GOLD if i == 9 else "white")
            else:
                cell(x, y, w, t, fills[i])
            x += w
        y += rh
    img = img.crop((0, 0, W, y + pad))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":  # pragma: no cover
    sys.exit("render is called by run.py")
