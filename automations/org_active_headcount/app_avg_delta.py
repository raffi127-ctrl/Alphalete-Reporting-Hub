"""Org Active Headcount -- the App Avg week-over-week picture.

Rafael 2026-11-08 (email): "Similar to the active headcount can we do a WoW
delta display of the app average please?" The numbers were already in the delta
box (its App Avg This week / Last week / Delta columns), but ranked by HEADCOUNT
and sitting beside it. This draws them as their own table, ranked like the
headcount one: highest This week first, ties by name.

Reads the tab's cells only (nothing is written, nothing new to roll), so it can
never disagree with the delta box. Drawn in org_split's look.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from automations.org_active_headcount import daily as d
from automations.org_active_headcount import org_split as o

Row = Tuple[str, str, str, str]


def _rank_key(row: Row):
    return (-(o._float(row[1]) or 0.0), row[0].lower())


def table(g) -> Tuple[str, List[Row], Row]:
    """(caption, owners ranked, totals) as the tab SHOWS them: '7.0', '6.06%'.
    Raises when the delta box has no App Avg columns, like every other reshape
    of this tab: better an alert than a mail missing a picture."""
    dx = d.find_delta(g)
    k = dx["avg"]
    if not k:
        raise ValueError("delta box: no 'App Avg' columns")

    def cells(r):
        return tuple(d._c(g, r, c) for c in (k, k + 1, k + 2))

    rows = [(name,) + cells(r) for r, name in dx["rows"]]
    return (d._c(g, dx["hdr"], dx["week"]), sorted(rows, key=_rank_key),
            ("Totals",) + cells(dx["totals"]))


def render(out_path: Path, g) -> Path:
    from PIL import Image, ImageDraw
    caption, rows, totals = table(g)
    f, ft, fb = o._font(22), o._font(34), o._font(24)
    widths = [64, 340, 150, 150, 150]
    rh, pad, th = 44, 16, 64
    W = sum(widths) + 2 * pad
    H = 2 * pad + th + rh * (len(rows) + 3)
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)

    def text_c(x, y, w, h, t, font, fill="black"):
        tw = dr.textlength(t, font=font)
        bb = font.getbbox("Hg")
        dr.text((x + (w - tw) / 2, y + (h - (bb[3] - bb[1])) / 2 - bb[1]), t,
                font=font, fill=fill)

    def line(y, vals, kind):
        x = pad
        for i, (w, t) in enumerate(zip(widths, vals)):
            fill = o.GREY if (kind != "row" or i < 2) else o.WHITE
            if kind != "hdr" and i == 4 and o._float(t.rstrip("%")):
                fill = o.RED if t.startswith("-") else o.GREEN
            dr.rectangle([x, y, x + w, y + rh], fill=fill, outline=o.BORDER)
            text_c(x, y, w, rh, t, f)
            x += w

    dr.rectangle([pad, pad, W - pad, pad + th], fill=o.TITLE_BG, outline=o.BORDER)
    text_c(pad, pad, W - 2 * pad, th, "App Avg - Week over Week", ft, (192, 0, 0))
    y = pad + th
    dr.rectangle([pad, y, W - pad, y + rh], fill=o.ORANGE, outline=o.BORDER)
    text_c(pad, y, W - 2 * pad, rh, caption or "This week vs last week", fb, "white")
    y += rh
    line(y, ["", "Owner", "This week", "Last week", "Delta"], "hdr")
    y += rh
    for n, row in enumerate(rows, 1):
        line(y, [str(n)] + list(row), "row")
        y += rh
    line(y, [""] + list(totals), "total")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
