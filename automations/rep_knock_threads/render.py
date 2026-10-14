"""Draw one rep's weekly knocking card as a PNG (Pillow, cross-platform fonts).

  ┌ title: rep · day · as-of ──────────────────────────────────────┐
  │ TODAY: GPS failed % · streak · doors · gap · talk-to · verified │
  │ ONGOING VITALS (week): same tiles · dispositions │ Mon–Sun grid  │
  │ DOORS THIS WEEK: a banner per day, then every door — red = GPS ✗ │
  └────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw

from automations.rep_knock_threads import config as C
from automations.rep_knock_threads.pull import gps_kind, gps_short
from automations.rep_knock_threads.stats import parse_when
from automations.total_knocks.render import _font

W = 1200
PAD = 28
INK = (31, 31, 31)
MUTED = (110, 110, 110)
LINE = (225, 222, 216)
BG = (255, 255, 255)
STRIPE = (248, 246, 242)
TITLE_BG = (60, 47, 36)
GOOD = (21, 128, 61)
GOOD_BG = (220, 252, 231)
BAD = (185, 28, 28)
BAD_BG = (254, 226, 226)
WARN_BG = (254, 243, 199)


def _hex(c: str) -> tuple:
    c = (c or "#CCCCCC").lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (204, 204, 204)


def _on(rgb: tuple) -> tuple:
    """Black or white text, whichever reads on this background."""
    r, g, b = rgb
    return INK if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else (255, 255, 255)


def _tw(d, text, font) -> int:
    return int(d.textlength(text, font=font))


def _clip(d, text, font, w) -> str:
    if _tw(d, text, font) <= w:
        return text
    while text and _tw(d, text + "…", font) > w:
        text = text[:-1]
    return text + "…"


def _pct(p: float) -> str:
    """'<1%' rather than a misleading '0%' for a door or two."""
    return "<1%" if 0 < p < 0.5 else f"{p:.0f}%"


def _hm(t: "dt.datetime | None") -> str:
    if not t:
        return "—"
    return t.strftime("%I:%M %p").lstrip("0")


def _week_label(days: list[dict]) -> str:
    a, b = days[0]["date"], days[-1]["date"]
    if a.month == b.month:
        return f"Week of {a:%b} {a.day} – {b.day}"
    return f"Week of {a:%b} {a.day} – {b:%b} {b.day}"


def _tiles(d, y, tiles, f_lab, f_kpi) -> int:
    tw = (W - 2 * PAD - (len(tiles) - 1) * 12) // len(tiles)
    for i, (lab, val, bg, fg, sub) in enumerate(tiles):
        x = PAD + i * (tw + 12)
        d.rounded_rectangle([x, y, x + tw, y + 110], 10, fill=bg)
        d.text((x + 14, y + 14), lab, font=f_lab, fill=MUTED)
        d.text((x + 14, y + 44), val, font=f_kpi, fill=fg)
        if sub:
            d.text((x + 14, y + 84), sub, font=f_lab, fill=fg if fg != INK else MUTED)
    return y + 110




ROW_H = 30
BANNER_H, BANNER_GAP = 40, 22
TCOLS = [("Time", PAD, 90), ("Address", PAD + 100, 520),
         ("Disposition", PAD + 640, 280), ("GPS", PAD + 940, W - 2 * PAD - 940)]


def _day_over(day: dict) -> bool:
    fp = 100.0 * day["fails"] / day["knocks"] if day["knocks"] else 0
    return day["knocks"] >= C.FLAG_MIN_KNOCKS and fp >= C.FLAG_FAIL_PCT


def _log_groups(s: dict) -> list:
    """[(day, rows newest-first, dropped)] for each worked day, newest day first."""
    groups, left = [], C.MAX_LOG_ROWS
    for day in reversed(s["days"]):
        if day["future"] or not day["knocks"]:
            continue
        drows = sorted((r for r in s["rows"] if r["when"][:10] == day["date"].isoformat()),
                       key=lambda r: r["when"], reverse=True)
        keep = drows[:max(left, 0)]
        left -= len(keep)
        groups.append((day, keep, len(drows) - len(keep)))
    return groups


def render(s: dict, *, as_of: dt.datetime, out: Path) -> Path:
    """Today's tiles → ongoing vitals (week so far) → every door this week,
    one banner per day (Megan 2026-10-14)."""
    f_title = _font(30, True)
    f_sub = _font(18)
    f_sec = _font(20, True)
    f_h = _font(17, True)
    f_kpi = _font(34, True)
    f_lab = _font(15)
    f_ban = _font(18, True)
    f = _font(16)
    f_b = _font(16, True)
    t = s["today"]
    today = next((dd["date"] for dd in reversed(s["days"]) if not dd["future"]),
                 s["days"][0]["date"])

    groups = _log_groups(s)
    today_h = 40 + 110 + 48
    vitals_h = 30 + 44 + 110 + 30 + max(44 + 30 * max(len(s["disp"]), 7), 44 + 30 * 8)
    log_h = 30 + 34 + ROW_H + len(groups) * (BANNER_GAP + BANNER_H) \
        + ROW_H * sum(len(g[1]) for g in groups) + 30 * sum(1 for g in groups if g[2]) \
        + (ROW_H if not groups else 0)
    H = 80 + 20 + today_h + vitals_h + log_h + 60

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ── title ───────────────────────────────────────────────────────────
    d.rectangle([0, 0, W, 80], fill=TITLE_BG)
    d.text((PAD, 14), s["rep"], font=f_title, fill=(255, 255, 255))
    d.text((PAD, 52), f"#{s['rep_id']} · Knocking Data", font=f_lab,
           fill=(220, 210, 195))
    right = f"{today:%a} {today.month}/{today.day}  ·  as of {_hm(as_of)} CT"
    d.text((W - PAD - _tw(d, right, f_sub), 30), right, font=f_sub,
           fill=(255, 255, 255))
    y = 100

    # ── TODAY ───────────────────────────────────────────────────────────
    d.text((PAD, y), "Today", font=f_sec, fill=INK)
    y += 40
    why = ", ".join(f"{c} {w.lower()}" for w, c in t["fail_reasons"][:2])
    streak_txt = (f"{s['streak']} day{'s' if s['streak'] != 1 else ''}"
                  if s["streak"] else "—")
    # No doors yet today (a streak carried in from the morning reset) → dashes,
    # not a misleading "0% verified".
    tp = (lambda v: _pct(v)) if t["knocks"] else (lambda v: "—")
    y = _tiles(d, y, [
        ("GPS failed today", tp(t["gps_fail_pct"]),
         BAD_BG if s["flagged"] else (WARN_BG if t["gps_fail"] else STRIPE),
         BAD if t["gps_fail"] else INK,
         f"{t['gps_fail']} of {t['knocks']} doors" if t["knocks"] else "no doors yet"),
        (f"Streak over {C.FLAG_FAIL_PCT:.0f}%", streak_txt,
         BAD_BG if s["streak"] else STRIPE, BAD if s["streak"] else INK,
         "in a row" if s["streak"] else ""),
        ("Doors today", f"{t['knocks']:,}", STRIPE, INK, ""),
        ("Avg min between doors", "—" if t["avg_gap"] is None else f"{t['avg_gap']:.1f}",
         STRIPE, INK, ""),
        ("Talk-to %", tp(t["talk_pct"]), STRIPE, INK, ""),
        ("GPS verified", tp(t["gps_ok_pct"]), GOOD_BG if t["knocks"] else STRIPE,
         GOOD if t["knocks"] else INK, ""),
    ], f_lab, f_kpi)
    if why:
        d.text((PAD, y + 10), "Failures: " + why, font=f_lab, fill=BAD)
    y += 48

    # ── ONGOING VITALS (week so far) ────────────────────────────────────
    d.line([PAD, y, W - PAD, y], fill=LINE, width=2)
    y += 30
    d.text((PAD, y - 14), f"Ongoing vitals — {_week_label(s['days'])}", font=f_sec, fill=INK)
    y += 30
    y = _tiles(d, y, [
        ("Doors this week", f"{s['knocks']:,}", STRIPE, INK, ""),
        ("Avg min between doors", "—" if s["avg_gap"] is None else f"{s['avg_gap']:.1f}",
         STRIPE, INK, ""),
        ("Talk-to %", _pct(s["talk_pct"]), STRIPE, INK, f"{s['talk_to']:,} doors"),
        ("GPS verified", _pct(s["gps_ok_pct"]), GOOD_BG, GOOD, ""),
        ("GPS failed", _pct(s["gps_fail_pct"]),
         BAD_BG if s["gps_fail_pct"] >= C.FLAG_FAIL_PCT else
         (WARN_BG if s["gps_fail"] else STRIPE),
         BAD if s["gps_fail"] else INK, f"{s['gps_fail']:,} doors" if s["gps_fail"] else ""),
        ("No GPS data", _pct(s["gps_none_pct"]), STRIPE, INK, ""),
    ], f_lab, f_kpi)
    y += 30

    lw = 560
    d.text((PAD, y), "Dispositions this week", font=f_h, fill=INK)
    yy = y + 34
    for status, n in s["disp"]:
        p = 100.0 * n / s["knocks"] if s["knocks"] else 0
        rgb = _hex(s["colors"].get(status))
        d.rounded_rectangle([PAD, yy + 4, PAD + 16, yy + 20], 3, fill=rgb, outline=LINE)
        d.text((PAD + 26, yy + 2), _clip(d, status, f, 270), font=f, fill=INK)
        bx = PAD + 310
        d.rectangle([bx, yy + 6, bx + 150, yy + 18], fill=(240, 238, 234))
        d.rectangle([bx, yy + 6, bx + int(150 * p / 100), yy + 18], fill=rgb, outline=LINE)
        txt = f"{_pct(p)}  ({n})"
        d.text((PAD + lw - _tw(d, txt, f), yy + 2), txt, font=f, fill=INK)
        yy += 30

    gx = PAD + lw + 40
    d.text((gx, y), "By day", font=f_h, fill=INK)
    cols = [("Day", 0), ("Doors", 100), ("First", 170), ("Last", 260), ("GPS failed", 350)]
    yy = y + 34
    for name, off in cols:
        d.text((gx + off, yy), name, font=f_b, fill=MUTED)
    yy += 26
    for day in s["days"]:
        label = f"{day['date']:%a} {day['date'].month}/{day['date'].day}"
        fg = MUTED if day["future"] else INK
        fp = 100.0 * day["fails"] / day["knocks"] if day["knocks"] else 0
        bad = _day_over(day)
        if bad:
            d.rectangle([gx + 340, yy - 2, W - PAD, yy + 24], fill=BAD_BG)
        fail_txt = f"{_pct(fp)} ({day['fails']})" if day["fails"] else "0"
        vals = [label,
                "" if day["future"] else str(day["knocks"]),
                "" if day["future"] else _hm(day["first"]),
                "" if day["future"] else _hm(day["last"]),
                "" if day["future"] or not day["knocks"] else fail_txt]
        for (name, off), v in zip(cols, vals):
            color = BAD if (name == "GPS failed" and day["fails"]) else fg
            d.text((gx + off, yy), v, font=f_b if (bad and name == "GPS failed") else f,
                   fill=color)
        yy += 30
    y = y + max(44 + 30 * max(len(s["disp"]), 7), 44 + 30 * 8)

    # ── DOORS THIS WEEK, one block per day ──────────────────────────────
    y += 30
    d.text((PAD, y), "Doors this week — newest first", font=f_sec, fill=INK)
    y += 34
    d.rectangle([PAD, y - 4, W - PAD, y + ROW_H - 6], fill=TITLE_BG)
    for name, x, _w in TCOLS:
        d.text((x + 6, y), name, font=f_b, fill=(255, 255, 255))
    y += ROW_H
    if not groups:
        d.text((PAD + 6, y + 4), "No doors yet this week.", font=f, fill=MUTED)
        y += ROW_H
    for day, drows, dropped in groups:
        # Day banner — a full-width bar; red when that day was over the line.
        y += BANNER_GAP
        fp = 100.0 * day["fails"] / day["knocks"] if day["knocks"] else 0
        d.rounded_rectangle([PAD, y, W - PAD, y + BANNER_H - 6], 6,
                            fill=BAD if _day_over(day) else (90, 74, 60))
        label = f"{day['date']:%A} {day['date'].month}/{day['date'].day}".upper() \
            + ("  ·  TODAY" if day["date"] == today else "")
        d.text((PAD + 14, y + 7), label, font=f_ban, fill=(255, 255, 255))
        info = f"{day['knocks']} doors  ·  GPS failed {_pct(fp)} ({day['fails']})"
        d.text((W - PAD - 14 - _tw(d, info, f_ban), y + 7), info, font=f_ban,
               fill=(255, 255, 255))
        y += BANNER_H
        for i, r in enumerate(drows):
            fail = gps_kind(r["gps"]) == "fail"
            if fail:
                d.rectangle([PAD, y - 2, W - PAD, y + ROW_H - 4], fill=BAD_BG)
            elif i % 2:
                d.rectangle([PAD, y - 2, W - PAD, y + ROW_H - 4], fill=STRIPE)
            d.text((TCOLS[0][1] + 6, y + 3), _hm(parse_when(r["when"])), font=f, fill=INK)
            d.text((TCOLS[1][1] + 6, y + 3), _clip(d, r["address"], f, TCOLS[1][2] - 12),
                   font=f, fill=INK)
            rgb = _hex(r["color"])
            cx = TCOLS[2][1] + 6
            lab = _clip(d, r["status"], f, TCOLS[2][2] - 30)
            d.rounded_rectangle([cx, y, cx + _tw(d, lab, f) + 16, y + 24], 6, fill=rgb)
            d.text((cx + 8, y + 3), lab, font=f, fill=_on(rgb))
            d.text((TCOLS[3][1] + 6, y + 3), gps_short(r["gps"]), font=f_b if fail else f,
                   fill=BAD if fail else (MUTED if gps_kind(r["gps"]) == "none" else GOOD))
            y += ROW_H
        if dropped:
            d.text((PAD + 6, y + 4), f"+ {dropped} more doors this day not shown",
                   font=f_lab, fill=MUTED)
            y += 30

    foot = ("Source: OwnerVille → TeleMapper Leads → Today's Activity → Lead Knocks "
            f"(GPS Status column). Posted when today's GPS failures reach "
            f"{C.FLAG_FAIL_PCT:.0f}% ({C.FLAG_MIN_KNOCKS}+ doors). Avg min between doors "
            f"leaves out gaps over {C.GAP_CAP_MIN} min. Talk-to = every door except "
            "No Answer / Inaccessible.")
    d.text((PAD, H - 34), _clip(d, foot, f_lab, W - 2 * PAD), font=f_lab, fill=MUTED)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out
