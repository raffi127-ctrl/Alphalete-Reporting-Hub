"""Draw one rep's day as a spreadsheet-style picture (Raf: "it just gets put up
in a spreadsheet ... color coordinate like the way it has here").

Newest knock on top, like OwnerVille. Status pills use OwnerVille's own colors
(read off each row, so a new status brings its color with it). GPS failures are
red; a run of FAIL_STREAK+ failures in a row is shaded red across the whole row,
which is the thing Raf wants caught at a glance.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from automations.rep_knock_breakdown import config as C
from automations.rep_knock_breakdown import streaks as S

W = 1180
PAD = 24
ROW_H = 40
HEAD_H = 92
TILES_H = 96
COLS = [("Time", 100), ("Address", 400), ("Status", 270), ("Last Note", 150),
        ("GPS", 212)]

INK = (33, 37, 41)
MUTED = (110, 117, 125)
GRID = (226, 229, 233)
BAND = (35, 47, 62)
RED = (200, 35, 51)
RED_BG = (253, 226, 226)
GREEN = (25, 135, 84)
ZEBRA = (248, 249, 250)

_FONTS = {
    True: ("C:/Windows/Fonts/arialbd.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "/Library/Fonts/Arial Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    False: ("C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
}
_cache: Dict = {}


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    key = (size, bold)
    if key not in _cache:
        for p in _FONTS[bold]:
            try:
                _cache[key] = ImageFont.truetype(p, size)
                break
            except Exception:  # noqa: BLE001
                continue
        else:
            _cache[key] = ImageFont.load_default()
    return _cache[key]


def _hex(h: str, default=(108, 117, 125)):
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return default
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def _text_on(bg) -> tuple:
    r, g, b = bg
    return INK if (0.299 * r + 0.587 * g + 0.114 * b) > 170 else (255, 255, 255)


def _short_span(span: str) -> str:
    """'5 hours, 53 min' -> '5h 53m' (fits its tile)."""
    import re
    m = re.match(r"\s*(\d+)\s+hours?,\s*(\d+)\s+min", span or "")
    return "%sh %sm" % m.groups() if m else (span or "—")


def _fit(draw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def render(rep: Dict, day_label: str, asof_label: str, out_dir: Path) -> List[Path]:
    """-> one PNG per ROWS_PER_IMAGE rows (at least one)."""
    from PIL import Image, ImageDraw

    rows = rep["rows"]
    seq = S.chronological(rows)
    streak_rows = set()
    for s, e in S.fail_streaks(rows, C.FAIL_STREAK):
        streak_rows.update(id(seq[i]) for i in range(s, e + 1))
    newest_first = list(reversed(seq))
    summ = S.summary(rows)

    pages = [newest_first[i:i + C.ROWS_PER_IMAGE]
             for i in range(0, len(newest_first), C.ROWS_PER_IMAGE)] or [[]]
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "_" for ch in rep["name"]).strip("_")
    paths = []
    for pi, chunk in enumerate(pages):
        first_page = pi == 0
        h = (HEAD_H + (TILES_H if first_page else 0) + ROW_H
             + ROW_H * max(len(chunk), 1) + PAD)
        im = Image.new("RGB", (W, h), (255, 255, 255))
        d = ImageDraw.Draw(im)

        # title band
        d.rectangle([0, 0, W, HEAD_H], fill=BAND)
        d.text((PAD, 16), _fit(d, rep["name"], _font(30, True), W - 2 * PAD),
               font=_font(30, True), fill=(255, 255, 255))
        sub = "Knocking data  ·  %s  ·  as of %s" % (day_label, asof_label)
        if len(pages) > 1:
            sub += "  ·  page %d of %d" % (pi + 1, len(pages))
        d.text((PAD, 56), sub, font=_font(18), fill=(200, 210, 222))
        y = HEAD_H

        if first_page:
            tiles = [
                ("Knocks", str(summ["knocks"]), INK),
                ("First knock", summ["first"] or "—", INK),
                ("Last knock", summ["last"] or "—", INK),
                ("Time knocking", _short_span(rep.get("time_knocking")), INK),
                ("GPS fails", str(summ["gps_fails"]),
                 RED if summ["gps_fails"] else GREEN),
                ("Most fails in a row", str(summ["longest_fail_run"]),
                 RED if summ["longest_fail_run"] >= C.FAIL_STREAK else INK),
            ]
            tw = (W - 2 * PAD) // len(tiles)
            for i, (label, val, color) in enumerate(tiles):
                x = PAD + i * tw
                d.text((x, y + 16), label.upper(), font=_font(13, True), fill=MUTED)
                d.text((x, y + 38), _fit(d, val, _font(26, True), tw - 10),
                       font=_font(26, True), fill=color)
            y += TILES_H

        # header row
        d.rectangle([0, y, W, y + ROW_H], fill=(241, 243, 245))
        x = PAD
        for name, cw in COLS:
            d.text((x, y + 11), name, font=_font(16, True), fill=INK)
            x += cw
        y += ROW_H

        if not chunk:
            d.text((PAD, y + 10), "No knocks yet.", font=_font(16), fill=MUTED)
        for ri, r in enumerate(chunk):
            hot = id(r) in streak_rows
            bg = RED_BG if hot else (ZEBRA if ri % 2 else (255, 255, 255))
            d.rectangle([0, y, W, y + ROW_H], fill=bg)
            if hot:
                d.rectangle([0, y, 6, y + ROW_H], fill=RED)
            d.line([0, y + ROW_H, W, y + ROW_H], fill=GRID)
            x = PAD
            f = _font(16)
            # time
            d.text((x, y + 11), r.get("time", ""), font=f, fill=INK)
            x += COLS[0][1]
            # address
            d.text((x, y + 11), _fit(d, r.get("address", ""), f, COLS[1][1] - 14),
                   font=f, fill=INK)
            x += COLS[1][1]
            # status pill
            pill = _hex(r.get("color", ""))
            label = _fit(d, r.get("status", ""), _font(14, True), COLS[2][1] - 34)
            pw = int(d.textlength(label, font=_font(14, True))) + 20
            d.rounded_rectangle([x, y + 8, x + pw, y + ROW_H - 8], radius=11,
                                fill=pill)
            d.text((x + 10, y + 12), label, font=_font(14, True), fill=_text_on(pill))
            x += COLS[2][1]
            # last note
            note = r.get("last_note", "")
            d.text((x, y + 11), _fit(d, note, f, COLS[3][1] - 14), font=f,
                   fill=MUTED)
            x += COLS[3][1]
            # gps
            gps = r.get("gps", "")
            dist = S.distance_text(gps)
            if S.gps_failed(r):
                txt, col, fnt = ("FAIL  " + dist).strip(), RED, _font(16, True)
            elif gps.lower().startswith("success"):
                txt, col, fnt = ("OK  " + dist).strip(), GREEN, f
            else:
                txt, col, fnt = (gps or "—"), MUTED, f
            d.text((x, y + 11), _fit(d, txt, fnt, COLS[4][1] - 6), font=fnt,
                   fill=col)
            y += ROW_H

        p = out_dir / ("%s_%d.png" % (slug, pi + 1))
        im.save(p)
        paths.append(p)
    return paths
