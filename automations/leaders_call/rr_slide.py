"""Alphalete Leader's Call — the R&R 2026 (Cancún) closing slide.

The deck's LAST page. Re-cuts Maud's 24x36 R&R poster
(resources/rr-2026-cancun-poster.png) into the deck's 16:9 widescreen page,
same vibe and the same words: sunset sky, sun on the horizon, palms, the
"TOP LEADERS INVITED" sticker, and the black qualifier panel with the two
villa photos (cropped straight out of the poster into resources/rr-villa-*.png).

Drawn as a single full-bleed Flowable rather than in the page callback: the
deck's onLaterPages handler paints the near-black ground on EVERY page before
any flowable renders, so a slide that needs its own ground has to paint over
it from inside the story. The footer strip is redrawn here to match, page
number included (canvas.getPageNumber() - 1, same off-by-the-cover math the
deck's footer uses).

Numbers/dates live in RR — one place to edit when the trip details change.
"""
from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable

_RES = Path(__file__).resolve().parents[2] / "resources"
VILLA_1 = _RES / "rr-villa-1.png"
VILLA_2 = _RES / "rr-villa-2.png"

PAGE_W, PAGE_H = 13.333 * inch, 7.5 * inch

# The trip, exactly as the poster states it.
RR = {
    "title": "R&R",
    "year": "2026",
    "badge": ["TOP", "LEADERS", "INVITED"],
    "place": "Cancún",
    "tagline": "~ where the sun meets the sea ~",
    "dates": "OCTOBER 15 – 18",
    "resort": "MOON PALACE CANCÚN",
    "panel_title": "R&R QUALIFIER",
    "villa_label": "VILLA RENTAL",
    "villa_dates": "SUN 11TH – THU 15TH",
    "quals_label": "QUALIFICATIONS",
    "quals": ["2 LIVE PROMOTIONS", "50K SAVED BY 8/13/26"],
    "quals_note": "(Keys to Success)",
}

# Sampled off the poster so the slide reads as the same piece of art.
SKY = [(0.00, "#301C50"), (0.12, "#4A2561"), (0.24, "#7C2365"),
       (0.36, "#C2185B"), (0.46, "#E54A48"), (0.58, "#FF6F3C"),
       (0.72, "#FFB347"), (0.86, "#FED67C"), (1.00, "#FFE9A8")]
SUN = colors.HexColor("#FFE782")
SAND = colors.HexColor("#F6E3B0")
SEA = colors.HexColor("#7FC8C4")
NAVY = colors.HexColor("#26144B")          # the poster's Didone "Cancun"
CREAM = colors.HexColor("#F7F1E3")
FROND = colors.HexColor("#1A3A2E")
TRUNK = colors.HexColor("#2D1B4E")
PANEL = colors.HexColor("#0A0612")
NEON_Y = colors.HexColor("#FFDE00")
NEON_P = colors.HexColor("#FF1F7A")
BADGE = colors.HexColor("#D8145F")
GOLD = colors.HexColor("#FFD700")
GOLD_DIM = colors.HexColor("#C8A24A")
INK = colors.HexColor("#0C0C0F")
ICD = colors.HexColor("#C9CBD2")
WHITE = colors.HexColor("#F3F6FC")

FOOTER_H = 0.46 * inch

# Hero (left) column: everything is centred on HERO_X.
HERO_X = 3.72 * inch
PANEL_X0, PANEL_X1 = 7.66 * inch, 12.92 * inch
PANEL_Y0, PANEL_Y1 = 0.78 * inch, 6.98 * inch
PAD = 0.26 * inch


def _mix(c1, c2, t):
    return colors.Color(c1.red + (c2.red - c1.red) * t,
                        c1.green + (c2.green - c1.green) * t,
                        c1.blue + (c2.blue - c1.blue) * t)


def _sky(c):
    """Vertical sunset gradient, painted as thin strips (no linearGradient
    dependency — this renders the same on every reportlab we run)."""
    stops = [(p, colors.HexColor(h)) for p, h in SKY]
    n = 420
    strip = PAGE_H / n
    for i in range(n):
        f = i / (n - 1.0)                   # stop 0 = poster TOP = page top
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= f <= p1:
                t = 0.0 if p1 == p0 else (f - p0) / (p1 - p0)
                c.setFillColor(_mix(c0, c1, t))
                break
        c.rect(0, PAGE_H - (i + 1) * strip, PAGE_W, strip + 0.6, fill=1, stroke=0)


def _sun(c, cx, cy, r):
    c.saveState()
    for i in range(9, 0, -1):              # soft halo, then the disc
        c.setFillColor(SUN)
        c.setFillAlpha(0.055)
        c.circle(cx, cy, r * (1 + i * 0.075), fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setFillColor(SUN)
    c.circle(cx, cy, r, fill=1, stroke=0)
    c.restoreState()


def _palm(c, x, base_y, h, flip=False):
    """Flat two-tone palm, the poster's silhouette: a leaning tapered trunk and
    six fronds fanned off the crown."""
    s = -1 if flip else 1
    lean = 0.10 * h * s
    c.saveState()
    c.setFillColor(TRUNK)
    c.setStrokeColor(TRUNK)
    p = c.beginPath()
    p.moveTo(x - 0.028 * h, base_y)
    p.curveTo(x - 0.020 * h, base_y + h * 0.45,
              x + lean * 0.5 - 0.014 * h, base_y + h * 0.78,
              x + lean - 0.012 * h, base_y + h)
    p.lineTo(x + lean + 0.012 * h, base_y + h)
    p.curveTo(x + lean * 0.5 + 0.016 * h, base_y + h * 0.78,
              x + 0.026 * h, base_y + h * 0.45,
              x + 0.030 * h, base_y)
    p.close()
    c.drawPath(p, fill=1, stroke=0)

    cx, cy = x + lean, base_y + h
    c.setFillColor(FROND)
    for ang, scale in ((162, 1.00), (196, 0.86), (226, 0.72),
                       (314, 0.72), (346, 0.88), (18, 1.00)):
        a = math.radians(ang if not flip else 180 - ang)
        L = 0.40 * h * scale
        ex, ey = cx + math.cos(a) * L, cy + math.sin(a) * L - 0.10 * h
        mx, my = cx + math.cos(a) * L * 0.52, cy + math.sin(a) * L * 0.52 + 0.13 * h
        f = c.beginPath()
        f.moveTo(cx, cy)
        f.curveTo(mx, my, ex - 0.04 * h, ey + 0.05 * h, ex, ey)
        f.curveTo(ex - 0.10 * h, ey - 0.06 * h, mx, my - 0.155 * h, cx, cy - 0.030 * h)
        f.close()
        c.drawPath(f, fill=1, stroke=0)
    c.setFillColor(TRUNK)
    c.circle(cx, cy, 0.030 * h, fill=1, stroke=0)
    c.restoreState()


def _shadow_text(c, x, y, text, font, size, fill, shadow, dx=3.0, dy=3.0,
                 tracking=0.0, centred=True):
    """The poster's offset-block lettering: a hard drop shadow, then the face."""
    for col, ox, oy in ((shadow, dx, -dy), (fill, 0, 0)):
        c.setFillColor(col)
        c.setFont(font, size)
        if tracking:
            w = c.stringWidth(text, font, size) + tracking * (len(text) - 1)
            cx = x - w / 2 if centred else x
            c.saveState()
            c.translate(ox, oy)
            for ch in text:
                c.drawString(cx, y, ch)
                cx += c.stringWidth(ch, font, size) + tracking
            c.restoreState()
        elif centred:
            c.drawCentredString(x + ox, y + oy, text)
        else:
            c.drawString(x + ox, y + oy, text)


def _badge(c, cx, cy, r):
    c.saveState()
    c.translate(cx, cy)
    c.rotate(9)
    c.setFillColor(BADGE)
    c.setStrokeColor(GOLD)
    c.setLineWidth(3.4)
    c.circle(0, 0, r, fill=1, stroke=1)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.0)
    c.circle(0, 0, r * 0.88, fill=0, stroke=1)
    c.setFillColor(NEON_Y)
    for i, line in enumerate(RR["badge"]):
        size = 15.5 if i == 1 else 14.5
        c.setFont("Helvetica-Bold", size)
        c.drawCentredString(0, 8 - i * 16.5, line)
    c.setFillColor(NEON_Y)
    for a in (90, 210, 330):
        _star(c, math.cos(math.radians(a)) * r * 0.72,
              math.sin(math.radians(a)) * r * 0.72 - 4, 5.0)
    c.restoreState()


def _star(c, cx, cy, r):
    p = c.beginPath()
    for i in range(10):
        a = math.radians(90 + i * 36)
        rad = r if i % 2 == 0 else r * 0.42
        (p.moveTo if i == 0 else p.lineTo)(cx + math.cos(a) * rad, cy + math.sin(a) * rad)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _hero(c):
    _sun(c, HERO_X, 4.62 * inch, 2.42 * inch)
    _palm(c, 0.62 * inch, 1.18 * inch, 3.15 * inch)
    _palm(c, 6.98 * inch, 1.18 * inch, 2.72 * inch, flip=True)

    _shadow_text(c, HERO_X, 6.28 * inch, RR["title"], "Helvetica-Bold", 96,
                 CREAM, NAVY, dx=6, dy=6, tracking=6)
    _shadow_text(c, HERO_X, 5.76 * inch, RR["year"], "Helvetica-Bold", 30,
                 CREAM, NAVY, dx=2.4, dy=2.4, tracking=13)

    c.setFillColor(NAVY)
    c.setFont("Times-Bold", 68)
    c.drawCentredString(HERO_X, 4.46 * inch, RR["place"])
    c.setFont("Times-Italic", 18)
    c.drawCentredString(HERO_X, 3.98 * inch, RR["tagline"])

    _shadow_text(c, HERO_X, 3.12 * inch, RR["dates"], "Helvetica-Bold", 32,
                 CREAM, colors.Color(0.15, 0.08, 0.29, 0.35), dx=2, dy=2, tracking=2)
    c.setStrokeColor(colors.Color(1, 1, 1, 0.55))
    c.setLineWidth(1.1)
    c.line(HERO_X - 1.55 * inch, 2.84 * inch, HERO_X + 1.55 * inch, 2.84 * inch)
    _shadow_text(c, HERO_X, 2.44 * inch, RR["resort"], "Helvetica-Bold", 16,
                 CREAM, colors.Color(0.15, 0.08, 0.29, 0.30), dx=1.4, dy=1.4, tracking=5)

    _badge(c, 6.62 * inch, 6.28 * inch, 0.80 * inch)


def _beach(c):
    """Sea line + sand the palms stand on, so the sun has a horizon."""
    c.saveState()
    c.setFillColor(SAND)
    c.rect(0, FOOTER_H, PAGE_W, 1.02 * inch - FOOTER_H, fill=1, stroke=0)
    for i in range(26):                    # feather the horizon into the sky
        c.setFillColor(colors.Color(SAND.red, SAND.green, SAND.blue,
                                    0.96 - i * 0.037))
        c.rect(0, (1.02 + i * 0.019) * inch, PAGE_W, 0.021 * inch, fill=1, stroke=0)
    c.restoreState()


def _photo(c, path, x, y, w):
    img = ImageReader(str(path))
    iw, ih = img.getSize()
    h = w * ih / iw
    c.drawImage(img, x, y - h, width=w, height=h, mask="auto")
    c.setStrokeColor(GOLD)
    c.setLineWidth(2.0)
    c.rect(x, y - h, w, h, fill=0, stroke=1)
    return h


def _panel(c):
    c.saveState()
    c.setFillColor(PANEL)
    c.setStrokeColor(GOLD)
    c.setLineWidth(2.6)
    c.roundRect(PANEL_X0, PANEL_Y0, PANEL_X1 - PANEL_X0, PANEL_Y1 - PANEL_Y0,
                12, fill=1, stroke=1)
    c.setStrokeColor(GOLD_DIM)
    c.setLineWidth(1.1)
    c.setDash(3, 4)
    i = 0.13 * inch
    c.roundRect(PANEL_X0 + i, PANEL_Y0 + i, PANEL_X1 - PANEL_X0 - 2 * i,
                PANEL_Y1 - PANEL_Y0 - 2 * i, 9, fill=0, stroke=1)
    c.setDash()

    cx = (PANEL_X0 + PANEL_X1) / 2
    x0, x1 = PANEL_X0 + PAD, PANEL_X1 - PAD
    inner_w = x1 - x0

    _shadow_text(c, cx, 6.30 * inch, RR["panel_title"], "Helvetica-Bold", 29,
                 NEON_Y, NEON_P, dx=2.6, dy=2.6, tracking=2)
    c.setFillColor(NEON_Y)
    for sx in (x0 + 0.16 * inch, x1 - 0.16 * inch):
        _star(c, sx, 6.40 * inch, 7.5)
    c.setStrokeColor(GOLD_DIM)
    c.setLineWidth(1.0)
    for sx0, sx1 in ((x0 + 0.34 * inch, x0 + 0.72 * inch),
                     (x1 - 0.72 * inch, x1 - 0.34 * inch)):
        c.line(sx0, 6.40 * inch, sx1, 6.40 * inch)

    gap = 0.14 * inch
    pw = (inner_w - gap) / 2
    top = 5.94 * inch
    _photo(c, VILLA_1, x0, top, pw)
    ph = _photo(c, VILLA_2, x0 + pw + gap, top, pw)

    y = top - ph - 0.60 * inch
    _shadow_text(c, cx, y, RR["villa_label"], "Helvetica-Bold", 26,
                 NEON_P, colors.Color(1, 1, 1, 0.22), dx=2, dy=2, tracking=3)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 17)
    c.drawCentredString(cx, y - 0.40 * inch, RR["villa_dates"])

    c.setStrokeColor(colors.Color(0.78, 0.64, 0.29, 0.55))
    c.setLineWidth(0.9)
    c.line(x0 + 0.9 * inch, y - 0.74 * inch, x1 - 0.9 * inch, y - 0.74 * inch)

    y2 = y - 1.20 * inch
    _shadow_text(c, cx, y2, RR["quals_label"], "Helvetica-Bold", 26,
                 NEON_P, colors.Color(1, 1, 1, 0.22), dx=2, dy=2, tracking=3)
    c.setFillColor(WHITE)
    for i, line in enumerate(RR["quals"]):
        c.setFont("Helvetica-Bold", 19)
        c.drawCentredString(cx, y2 - (0.48 + i * 0.40) * inch, line)
    c.setFillColor(ICD)
    c.setFont("Helvetica-Oblique", 13)
    c.drawCentredString(cx, y2 - 1.45 * inch, RR["quals_note"])
    c.restoreState()


def _footer(c, week_label):
    c.saveState()
    c.setFillColor(INK)
    c.rect(0, 0, PAGE_W, FOOTER_H, fill=1, stroke=0)
    c.setStrokeColor(GOLD_DIM)
    c.setLineWidth(0.8)
    c.line(0, FOOTER_H, PAGE_W, FOOTER_H)
    c.setFillColor(ICD)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(0.6 * inch, 0.17 * inch, f"Alphalete Leader's Call   ·   {week_label}")
    try:
        n = c.getPageNumber() - 1
    except Exception:
        n = ""
    c.drawRightString(PAGE_W - 0.6 * inch, 0.17 * inch, str(n))
    c.restoreState()


def draw_rr(c, week_label=""):
    """Paint the whole R&R slide onto `c` in PAGE coordinates."""
    _sky(c)
    _beach(c)
    _hero(c)
    _panel(c)
    _footer(c, week_label)


class RRSlide(Flowable):
    """Full-bleed R&R slide. Sized to the frame, but draws in page coordinates
    so it covers the deck's near-black ground and its footer."""

    def __init__(self, week_label=""):
        super().__init__()
        self.week_label = week_label

    def wrap(self, avail_w, avail_h):
        self.width, self.height = avail_w, avail_h
        return avail_w, avail_h

    def draw(self):
        c = self.canv
        ax, ay = c.absolutePosition(0, 0)
        c.saveState()
        c.translate(-ax, -ay)
        draw_rr(c, self.week_label)
        c.restoreState()
