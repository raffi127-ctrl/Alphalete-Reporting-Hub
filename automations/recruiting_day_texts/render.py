"""The morning picture: AppStream's 'Timeslot Totals' layout, three columns.

    1st Rounds | Total N     2nd Rounds | Total N     New Starts | Total N
    Time      #              Time      #              Name
    8:15 AM   2              8:45 AM   3              Arielle Adams
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

S = 2                                   # draw at 2x so it stays sharp on phones
BG, INK, GRID = "#FFFFFF", "#1F2937", "#D1D5DB"
RED = "#B91C1C"
HEAD_BG, SUB_BG, ZEBRA = "#1F3A5F", "#E5E7EB", "#F9FAFB"
HEAD_INK, MUTED = "#FFFFFF", "#6B7280"

_FONTS = {
    "bold": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "C:/Windows/Fonts/arialbd.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "reg": ["/System/Library/Fonts/Supplemental/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def _font(kind: str, size: int):
    for p in _FONTS[kind]:
        if Path(p).exists():
            return ImageFont.truetype(p, size * S)
    return ImageFont.load_default(size * S)


def fmt_time(t: dt.time) -> str:
    """8:15 AM -- no %-I (Windows)."""
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def fmt_day(d: dt.date) -> str:
    return "%s, %s %d" % (d.strftime("%A"), d.strftime("%b"), d.day)


def _table(draw, x: int, y: int, w: int, title: str, cols: Sequence[str],
           widths: Sequence[float], rows: List[Sequence[str]], empty: str) -> int:
    """Draw one boxed table; return its bottom y."""
    fh, fs, fr = _font("bold", 17), _font("bold", 14), _font("reg", 15)
    rh = 34 * S
    draw.rectangle([x, y, x + w, y + rh], fill=HEAD_BG)
    draw.text((x + 12 * S, y + rh / 2), title, font=fh, fill=HEAD_INK, anchor="lm")
    y += rh
    draw.rectangle([x, y, x + w, y + rh], fill=SUB_BG)
    cx = x
    for c, frac in zip(cols, widths):
        draw.text((cx + 12 * S, y + rh / 2), c, font=fs, fill=INK, anchor="lm")
        cx += int(w * frac)
    y += rh
    if not rows:
        rows, muted = [[empty]], True
    else:
        muted = False
    for i, r in enumerate(rows):
        if i % 2:
            draw.rectangle([x, y, x + w, y + rh], fill=ZEBRA)
        cx = x
        for v, frac in zip(r, widths):
            draw.text((cx + 12 * S, y + rh / 2), str(v), font=fr,
                      fill=MUTED if muted else INK, anchor="lm")
            cx += int(w * frac)
        draw.line([x, y + rh, x + w, y + rh], fill=GRID, width=S)
        y += rh
    return y


def morning_png(day, out: Path, low: Optional[dict] = None) -> Path:
    """`day` = read.Day. `low` = {'first'|'second': usual avg} for a count that
    is clearly under its usual: its header gets a red * and a red note goes
    under the tables. Writes and returns the PNG."""
    low = low or {}
    first = [(fmt_time(t), n) for t, n in day.slots("first")]
    second = [(fmt_time(t), n) for t, n in day.slots("second")]
    timed = day.ns_with_times()
    has_t = any(t for t, _ in timed)
    starts = ([(fmt_time(t) if t else "\u2014", n) for t, n in timed] if has_t
              else [(n,) for _, n in timed])
    pad, colw, gap = 24 * S, 300 * S, 24 * S
    width = pad * 2 + colw * 3 + gap * 2
    rows = max(len(first), len(second), len(starts), 1)
    height = pad + 60 * S + (2 + rows) * 34 * S + pad + 30 * S
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.text((pad, pad), "%s  |  %s" % (day.owner, fmt_day(day.day)),
           font=_font("bold", 22), fill=INK)
    d.text((pad, pad + 32 * S), "Today's schedule from AppStream",
           font=_font("reg", 14), fill=MUTED)
    top = pad + 60 * S
    star = lambda k: "  *" if k in low else ""
    bottoms = [
        _table(d, pad, top, colw, "1st Rounds  |  Total: %d%s" % (len(day.first), star("first")),
               ["Time", "Interviews"], [0.5, 0.5], first, "None today"),
        _table(d, pad + colw + gap, top, colw,
               "2nd Rounds  |  Total: %d%s" % (len(day.second), star("second")),
               ["Time", "Interviews"], [0.5, 0.5], second, "None today"),
        _table(d, pad + 2 * (colw + gap), top, colw,
               "New Starts  |  Total: %d" % len(day.ns_scheduled),
               ["Time", "Name"] if has_t else ["Name"],
               [0.32, 0.68] if has_t else [1.0], starts, "None today"),
    ]
    y = max(bottoms) + pad
    if low:
        wd = day.day.strftime("%A")
        lines = ["* Lower than usual: " + ",  ".join(
                    "%s %d today vs about %.0f on a normal %s"
                    % ({"first": "1st rounds", "second": "2nd rounds"}[k],
                       len(getattr(day, k)), a, wd)
                    for k, a in sorted(low.items())),
                 "  You may want to reach out to your recruiting team."]
        canvas = Image.new("RGB", (width, y + len(lines) * 30 * S + pad), BG)
        canvas.paste(img.crop((0, 0, width, y)), (0, 0))
        d2 = ImageDraw.Draw(canvas)
        for i, ln in enumerate(lines):
            d2.text((pad, y + i * 30 * S), ln, font=_font("bold", 16), fill=RED)
        img, y = canvas, y + len(lines) * 30 * S
    img = img.crop((0, 0, width, y + pad // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


GREEN = "#15803D"


def showed_png(day, out: Path) -> Path:
    """4pm picture: every new start scheduled today, showed or not.

    Showed first, then no-shows, alphabetical within each. Anyone marked
    showed who was not on today's scheduled list (rescheduled in) is still
    listed as showed -- AppStream counted them.
    """
    came = {n.lower() for n in day.ns_showed}
    sched = list(day.ns_scheduled)
    extra = [n for n in day.ns_showed if n.lower() not in {s.lower() for s in sched}]
    people = sorted(((n, n.lower() in came) for n in sched + extra),
                    key=lambda p: (not p[1], p[0].lower()))
    n_s, n_c = len(day.ns_scheduled), len(day.ns_showed)
    pct = int(round(100.0 * n_c / n_s)) if n_s else 0

    pad, w = 24 * S, 560 * S
    rh = 34 * S
    height = pad + 96 * S + (2 + max(len(people), 1)) * rh + pad
    img = Image.new("RGB", (pad * 2 + w, height), BG)
    d = ImageDraw.Draw(img)
    d.text((pad, pad), "%s  |  %s" % (day.owner, fmt_day(day.day)),
           font=_font("bold", 22), fill=INK)
    d.text((pad, pad + 34 * S), "%d/%d new starts showed  —  %d%% retention"
           % (n_c, n_s, pct), font=_font("bold", 18), fill=GREEN if pct >= 50 else RED)
    d.text((pad, pad + 64 * S), "From AppStream Retention Details",
           font=_font("reg", 14), fill=MUTED)
    y = pad + 96 * S
    fh, fs, fr = _font("bold", 17), _font("bold", 14), _font("reg", 15)
    d.rectangle([pad, y, pad + w, y + rh], fill=HEAD_BG)
    d.text((pad + 12 * S, y + rh / 2), "New Starts  |  Total: %d" % n_s,
           font=fh, fill=HEAD_INK, anchor="lm")
    y += rh
    d.rectangle([pad, y, pad + w, y + rh], fill=SUB_BG)
    d.text((pad + 12 * S, y + rh / 2), "Name", font=fs, fill=INK, anchor="lm")
    d.text((pad + int(w * 0.68), y + rh / 2), "1st Day", font=fs, fill=INK, anchor="lm")
    y += rh
    for i, (name, ok) in enumerate(people):
        if i % 2:
            d.rectangle([pad, y, pad + w, y + rh], fill=ZEBRA)
        d.text((pad + 12 * S, y + rh / 2), name, font=fr, fill=INK, anchor="lm")
        d.text((pad + int(w * 0.68), y + rh / 2), "Showed" if ok else "No show",
               font=_font("bold", 15), fill=GREEN if ok else RED, anchor="lm")
        d.line([pad, y + rh, pad + w, y + rh], fill=GRID, width=S)
        y += rh
    img = img.crop((0, 0, pad * 2 + w, y + pad))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
